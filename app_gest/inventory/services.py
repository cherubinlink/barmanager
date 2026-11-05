from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.apps import apps
from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.utils import timezone

from catalog.models import ProductBar
from core.models import PaymentMethod, PeriodType

from .models import (DailyClosing, DailyClosingLine, InventoryCount, InventoryCountLine,
                     LossReport, StockLot, StockMovement)

ZERO = Decimal("0")
Kind = StockMovement.Kind
IN_KINDS = (Kind.OPENING, Kind.PURCHASE_IN)
LOSS_KINDS = (Kind.LOSS_OUT, Kind.FREE_OUT)


class InsufficientStock(Exception):
    pass


class InventoryError(Exception):
    pass


# ------------------------------------------------------------------ sorties / entrées de stock
@transaction.atomic
def consume_stock(*, bar, product_bar, qty, kind, ticket_line=None, loss_report=None,
                  user=None, allow_negative=False, business_date=None, note=""):
    """Sort `qty` unités en vidant d'abord le lot le plus ancien (FIFO).

    Retourne (mouvements, coût_des_marchandises_vendues). Verrouille les lots
    (select_for_update) : deux vendeuses ne peuvent pas vendre la dernière bouteille.
    """
    to_take = Decimal(qty)
    movements, cogs = [], Decimal("0")
    business_date = business_date or bar.current_business_date()

    for lot in StockLot.objects.fifo(bar, product_bar):
        if to_take <= 0:
            break
        take = min(lot.remaining_qty, to_take)
        lot.remaining_qty -= take
        if lot.remaining_qty == 0:
            lot.status = StockLot.Status.DEPLETED
        lot.save(update_fields=["remaining_qty", "status", "updated_at"])
        movements.append(StockMovement.objects.create(
            bar=bar, product_bar=product_bar, lot=lot, kind=kind, quantity=-take,
            unit_cost_fcfa=lot.unit_cost_fcfa, ticket_line=ticket_line,
            loss_report=loss_report, created_by=user, note=note,
            occurred_at=timezone.now(), business_date=business_date,
        ))
        cogs += take * lot.unit_cost_fcfa
        to_take -= take

    if to_take > 0:
        if not allow_negative:
            raise InsufficientStock(f"Stock insuffisant pour {product_bar} (manque {to_take}).")
        cost = Decimal(product_bar.purchase_price_fcfa)  # lot inconnu : dernier prix d'achat
        movements.append(StockMovement.objects.create(
            bar=bar, product_bar=product_bar, lot=None, kind=kind, quantity=-to_take,
            unit_cost_fcfa=cost, ticket_line=ticket_line, loss_report=loss_report,
            created_by=user, occurred_at=timezone.now(), business_date=business_date,
            note="Vente hors stock enregistré (à régulariser)",
        ))
        cogs += to_take * cost
    return movements, cogs


@transaction.atomic
def add_stock(*, bar, product_bar, qty, unit_cost, kind, source, user=None, note="",
              received_at=None, business_date=None):
    """Entrée de stock hors commande fournisseur : crée un lot ET son mouvement d'entrée."""
    qty = Decimal(qty)
    now = timezone.now()
    cost = Decimal(unit_cost).quantize(Decimal("0.01"))
    lot = StockLot.objects.create(
        bar=bar, product_bar=product_bar, source=source, received_at=received_at or now,
        initial_qty=qty, remaining_qty=qty, unit_cost_fcfa=cost)
    StockMovement.objects.create(
        bar=bar, product_bar=product_bar, lot=lot, kind=kind, quantity=qty, unit_cost_fcfa=cost,
        occurred_at=now, business_date=business_date or bar.current_business_date(),
        created_by=user, note=note)
    return lot


def date_to_datetime(day):
    return timezone.make_aware(datetime.combine(day, time.min))


# ------------------------------------------------------------------ lecture du stock
def stock_by_product(bar):
    """{id_produit_bar: {"qty", "value", "lots"}} calculé en UNE requête."""
    value = ExpressionWrapper(F("remaining_qty") * F("unit_cost_fcfa"),
                              output_field=DecimalField(max_digits=18, decimal_places=2))
    rows = (StockLot.objects.filter(bar=bar, status=StockLot.Status.OPEN, remaining_qty__gt=0)
            .values("product_bar_id")
            .annotate(qty=Sum("remaining_qty"), value=Sum(value), lots=Count("id")).order_by())
    return {r["product_bar_id"]: {"qty": r["qty"] or ZERO, "value": r["value"] or ZERO, "lots": r["lots"]}
            for r in rows}


def check_low_stock(bar, product_bar):
    """Alerte (une seule notification non lue par produit) quand le stock passe sous le seuil."""
    if not apps.is_installed("notifications"):
        return
    stock = product_bar.current_stock()
    if stock > product_bar.low_stock_threshold:
        return
    from accounts.permissions import Perm
    from notifications.models import Notification, NotificationType
    from notifications.services import notify_bar

    out = stock <= 0
    notify_bar(bar, type=NotificationType.STOCK_OUT if out else NotificationType.LOW_STOCK,
               title=f"{'Rupture' if out else 'Stock bas'} : {product_bar.product}",
               body=f"Il reste {stock.normalize():f} unité(s).", perm=Perm.STOCK_VIEW,
               level=Notification.Level.CRITICAL if out else Notification.Level.WARNING,
               url=f"/stock/produits/{product_bar.pk}/", dedup_key=f"low-stock:{product_bar.pk}")


# ------------------------------------------------------------------ périodes et rapport
def _month_end(day):
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def period_bounds(period_type, ref):
    if period_type == PeriodType.WEEK:
        start = ref - timedelta(days=ref.weekday())
        return start, start + timedelta(days=6)
    if period_type == PeriodType.MONTH:
        return ref.replace(day=1), _month_end(ref)
    if period_type == PeriodType.QUARTER:
        start = date(ref.year, ((ref.month - 1) // 3) * 3 + 1, 1)
        return start, _month_end(start.replace(month=start.month + 2))
    if period_type == PeriodType.YEAR:
        return date(ref.year, 1, 1), date(ref.year, 12, 31)
    return ref, ref


def movement_report(bar, start, end):
    """Inventaire d'une période (jour, semaine, mois, trimestre, année) calculé à partir du journal
    des mouvements : stock d'ouverture + entrées − ventes − pertes ± ajustements = stock de clôture."""
    value = ExpressionWrapper(F("quantity") * F("unit_cost_fcfa"),
                              output_field=DecimalField(max_digits=18, decimal_places=2))
    in_period = Q(business_date__gte=start)
    rows = (StockMovement.objects.filter(bar=bar, business_date__lte=end)
            .values("product_bar_id")
            .annotate(
                opening=Sum("quantity", filter=Q(business_date__lt=start)),
                purchased=Sum("quantity", filter=in_period & Q(kind__in=IN_KINDS)),
                returned=Sum("quantity", filter=in_period & Q(kind=Kind.RETURN_IN)),
                sold=Sum("quantity", filter=in_period & Q(kind=Kind.SALE_OUT)),
                lost=Sum("quantity", filter=in_period & Q(kind__in=LOSS_KINDS)),
                adj_in=Sum("quantity", filter=in_period & Q(kind=Kind.ADJUST_IN)),
                adj_out=Sum("quantity", filter=in_period & Q(kind=Kind.ADJUST_OUT)),
                purchase_value=Sum(value, filter=in_period & Q(kind__in=IN_KINDS)),
                cogs=Sum(value, filter=in_period & Q(kind=Kind.SALE_OUT)),
                loss_value=Sum(value, filter=in_period & Q(kind__in=LOSS_KINDS)),
            ).order_by())
    names = {pb.id: pb for pb in ProductBar.objects.filter(bar=bar).select_related("product__category")}
    report, totals = [], {k: ZERO for k in ("purchase_value", "cogs", "loss_value")}
    for r in rows:
        d = {k: (r[k] or ZERO) for k in r if k != "product_bar_id"}
        item = {
            "product_bar": names.get(r["product_bar_id"]),
            "opening": d["opening"], "purchased": d["purchased"] + d["returned"],
            "sold": -d["sold"], "lost": -d["lost"], "adjust": d["adj_in"] + d["adj_out"],
            "purchase_value": d["purchase_value"], "cogs": -d["cogs"], "loss_value": -d["loss_value"],
        }
        item["closing"] = (item["opening"] + item["purchased"] - item["sold"] - item["lost"] + item["adjust"])
        if any(item[k] for k in ("opening", "purchased", "sold", "lost", "adjust")) and item["product_bar"]:
            report.append(item)
            for k in totals:
                totals[k] += item[k]
    report.sort(key=lambda i: (i["product_bar"].product.category.name, i["product_bar"].product.name))
    return report, totals


# ------------------------------------------------------------------ pertes
@transaction.atomic
def approve_loss(report, user):
    report = LossReport.objects.select_for_update().select_related("product_bar").get(pk=report.pk)
    if report.status != LossReport.Status.PENDING:
        raise InventoryError("Cette perte a déjà été traitée.")
    kind = Kind.FREE_OUT if report.reason == LossReport.Reason.GIVEN else Kind.LOSS_OUT
    consume_stock(bar=report.bar, product_bar=report.product_bar, qty=report.quantity, kind=kind,
                  loss_report=report, user=user, business_date=report.business_date,
                  note=f"{report.get_reason_display()}{(' : ' + report.note) if report.note else ''}")
    report.status, report.reviewed_by, report.reviewed_at = LossReport.Status.APPROVED, user, timezone.now()
    report.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
    check_low_stock(report.bar, report.product_bar)
    return report


@transaction.atomic
def reject_loss(report, user):
    report = LossReport.objects.select_for_update().get(pk=report.pk)
    if report.status != LossReport.Status.PENDING:
        raise InventoryError("Cette perte a déjà été traitée.")
    report.status, report.reviewed_by, report.reviewed_at = LossReport.Status.REJECTED, user, timezone.now()
    report.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
    return report


# ------------------------------------------------------------------ inventaire physique
@transaction.atomic
def create_count(bar, period_type, ref_date, user, note=""):
    start, end = period_bounds(period_type, ref_date)
    count = InventoryCount.objects.create(bar=bar, period_type=period_type, period_start=start,
                                          period_end=end, counted_by=user, note=note)
    stock = stock_by_product(bar)
    lines = []
    for pb in ProductBar.objects.filter(bar=bar, is_active=True):
        s = stock.get(pb.id)
        qty = s["qty"] if s else ZERO
        cost = (s["value"] / s["qty"]).quantize(Decimal("0.01")) if s and s["qty"] else Decimal(pb.purchase_price_fcfa)
        lines.append(InventoryCountLine(count=count, product_bar=pb, theoretical_qty=qty, unit_cost_fcfa=cost))
    InventoryCountLine.objects.bulk_create(lines)
    return count


@transaction.atomic
def save_count_entries(count, entries):
    """entries = {id_ligne: quantité comptée ou None}. Rafraîchit aussi le stock théorique (stock au moment du comptage)."""
    stock = stock_by_product(count.bar)
    for line in count.lines.all():
        if line.id not in entries:
            continue
        qty = entries[line.id]
        line.counted_qty = qty
        line.theoretical_qty = stock.get(line.product_bar_id, {}).get("qty", ZERO)
        line.save(update_fields=["counted_qty", "theoretical_qty"])
    any_counted = count.lines.filter(counted_qty__isnull=False).exists()
    count.status = InventoryCount.Status.IN_PROGRESS if any_counted else InventoryCount.Status.DRAFT
    count.save(update_fields=["status", "updated_at"])


@transaction.atomic
def apply_count(count, user):
    """Valide l'inventaire : le stock du livre est ramené à la quantité comptée (écarts = ajustements)."""
    count = InventoryCount.objects.select_for_update().get(pk=count.pk)
    if count.status == InventoryCount.Status.VALIDATED:
        raise InventoryError("Cet inventaire est déjà validé.")
    lines = list(count.lines.select_related("product_bar"))
    if not any(l.counted_qty is not None for l in lines):
        raise InventoryError("Aucune quantité comptée : rien à valider.")
    stock = stock_by_product(count.bar)
    now_day, gaps = count.bar.current_business_date(), 0
    for line in lines:
        if line.counted_qty is None:
            continue
        current = stock.get(line.product_bar_id, {}).get("qty", ZERO)
        diff = line.counted_qty - current
        line.theoretical_qty = current
        if diff < 0:
            moves, _ = consume_stock(bar=count.bar, product_bar=line.product_bar, qty=-diff,
                                     kind=Kind.ADJUST_OUT, user=user, business_date=now_day,
                                     note=f"Inventaire du {count.period_end:%d/%m/%Y}")
            line.adjustment_movement = moves[0]
        elif diff > 0:
            cost = line.unit_cost_fcfa or Decimal(line.product_bar.purchase_price_fcfa)
            lot = add_stock(bar=count.bar, product_bar=line.product_bar, qty=diff, unit_cost=cost,
                            kind=Kind.ADJUST_IN, source=StockLot.Source.ADJUSTMENT, user=user,
                            note=f"Inventaire du {count.period_end:%d/%m/%Y}", business_date=now_day)
            line.adjustment_movement = lot.movements.first()
        line.save(update_fields=["theoretical_qty", "adjustment_movement"])
        if diff:
            gaps += 1
            check_low_stock(count.bar, line.product_bar)
    count.status, count.validated_by, count.validated_at = (
        InventoryCount.Status.VALIDATED, user, timezone.now())
    count.save(update_fields=["status", "validated_by", "validated_at", "updated_at"])
    return gaps


# ------------------------------------------------------------------ clôture journalière
def cash_expected(bar, day):
    from sales.models import Payment
    rows = (Payment.objects.filter(bar=bar, ticket__business_date=day, method=PaymentMethod.CASH)
            .values("kind").annotate(t=Sum("amount_fcfa")).order_by())
    total = 0
    for r in rows:
        total += -r["t"] if r["kind"] == Payment.Kind.REFUND else r["t"]
    return int(total)


def open_tickets_count(bar, day):
    from sales.models import Ticket
    return Ticket.objects.filter(bar=bar, business_date__lte=day, status__in=(
        Ticket.Status.OPEN, Ticket.Status.AWAITING_PAYMENT, Ticket.Status.PENDING_VALIDATION)).count()


@transaction.atomic
def close_day(bar, day, user, cash_counted=None, note=""):
    from sales.models import Ticket, TicketLine
    if DailyClosing.objects.filter(bar=bar, business_date=day).exists():
        raise InventoryError("Cette journée est déjà clôturée.")
    if open_tickets_count(bar, day):
        raise InventoryError("Il reste des tickets ouverts : finalisez-les ou annulez-les avant de clôturer.")
    closing = DailyClosing.objects.create(
        bar=bar, business_date=day, status=DailyClosing.Status.CLOSED, closed_by=user,
        closed_at=timezone.now(), cash_expected_fcfa=cash_expected(bar, day),
        cash_counted_fcfa=cash_counted, note=note)
    sales = {r["product_bar_id"]: r for r in (
        TicketLine.objects.filter(ticket__bar=bar, ticket__business_date=day, is_void=False)
        .exclude(ticket__status__in=(Ticket.Status.CANCELLED, Ticket.Status.PENDING_VALIDATION))
        .values("product_bar_id").annotate(revenue=Sum("line_total_fcfa"), cogs=Sum("cogs_fcfa")).order_by())}
    report, _ = movement_report(bar, day, day)
    lines = []
    for item in report:
        s = sales.get(item["product_bar"].id, {})
        lines.append(DailyClosingLine(
            closing=closing, product_bar=item["product_bar"], opening_qty=item["opening"],
            in_qty=item["purchased"], sold_qty=item["sold"], lost_qty=item["lost"],
            adjust_qty=item["adjust"], closing_qty=item["closing"],
            revenue_fcfa=int(s.get("revenue") or 0), cogs_fcfa=int(s.get("cogs") or 0)))
    DailyClosingLine.objects.bulk_create(lines)
    return closing