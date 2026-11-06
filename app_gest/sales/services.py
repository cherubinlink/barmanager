from decimal import Decimal

from django.apps import apps
from django.db import transaction
from django.db.models import BigIntegerField, Case, F, Sum, When
from django.utils import timezone

from core.models import PaymentMethod
from inventory.models import StockLot, StockMovement
from inventory.services import add_stock, check_low_stock, consume_stock

from .models import Customer, Payment, Ticket, TicketLine, TicketSequence

ZERO = Decimal("0")
Status = Ticket.Status
Kind = StockMovement.Kind
EDITABLE = (Status.OPEN, Status.AWAITING_PAYMENT, Status.PAID)          # lignes modifiables
PAYABLE = (Status.OPEN, Status.AWAITING_PAYMENT, Status.PAID, Status.FINALIZED)
EXCLUDED_FROM_SALES = (Status.CANCELLED, Status.PENDING_VALIDATION)


class SalesError(Exception):
    pass


# ------------------------------------------------------------------ utilitaires internes
def _lock(ticket):
    return Ticket.objects.select_for_update().get(pk=ticket.pk)


def _refresh(ticket):
    """Recalcule les totaux et aligne le statut (OPEN <-> PAID) sur l'état des paiements."""
    ticket.recalc(save=False)
    if ticket.status in (Status.OPEN, Status.AWAITING_PAYMENT, Status.PAID):
        if ticket.payment_status == Ticket.PaymentStatus.PAID and ticket.total_fcfa > 0:
            ticket.status = Status.PAID
        elif ticket.status == Status.PAID:
            ticket.status = Status.OPEN
    ticket.save(update_fields=["subtotal_fcfa", "total_fcfa", "amount_paid_fcfa", "payment_status",
                               "status", "updated_at"])


def _consume_line(line, ticket, user):
    """Sort la ligne du stock (FIFO) et fige son coût réel. La vente hors stock est tolérée (à régulariser)."""
    _, cogs = consume_stock(bar=ticket.bar, product_bar=line.product_bar, qty=line.base_quantity,
                            kind=Kind.SALE_OUT, ticket_line=line, user=user, allow_negative=True,
                            business_date=ticket.business_date, note=f"Vente {ticket.display_name}")
    line.cogs_fcfa, line.stock_consumed = cogs, True
    line.save(update_fields=["cogs_fcfa", "stock_consumed"])


def _return_line_stock(line, ticket, user, note):
    if not line.stock_consumed or line.base_quantity <= 0:
        return
    unit_cost = (line.cogs_fcfa / line.base_quantity) if line.cogs_fcfa else Decimal(line.product_bar.purchase_price_fcfa)
    add_stock(bar=ticket.bar, product_bar=line.product_bar, qty=line.base_quantity, unit_cost=unit_cost,
              kind=Kind.RETURN_IN, source=StockLot.Source.ADJUSTMENT, user=user, note=note,
              business_date=ticket.business_date)
    line.stock_consumed = False


# ------------------------------------------------------------------ tickets
@transaction.atomic
def open_ticket(bar, user, *, custom_name="", customer=None, table_label="", note="",
                payment_timing=Ticket.PaymentTiming.DEFERRED, source=Ticket.Source.POS):
    day, label = TicketSequence.next_label(bar)
    status = Status.OPEN if source == Ticket.Source.POS else Status.PENDING_VALIDATION
    return Ticket.objects.create(
        bar=bar, business_date=day, label=label, custom_name=custom_name, customer=customer,
        table_label=table_label, note=note, payment_timing=payment_timing, source=source,
        status=status, opened_by=user)


@transaction.atomic
def add_line(ticket, product_bar, qty, user, serving=None):
    ticket = _lock(ticket)
    if ticket.status not in EDITABLE:
        raise SalesError("Ce ticket n'est plus modifiable.")
    if product_bar.bar_id != ticket.bar_id:
        raise SalesError("Produit inconnu dans ce bar.")
    qty = Decimal(qty)
    if serving is not None:
        price, base = serving.price_fcfa, qty * serving.base_qty
    else:
        price, base = product_bar.sale_price_fcfa, qty
    line = TicketLine.objects.create(ticket=ticket, product_bar=product_bar, serving=serving, quantity=qty,
                                     unit_price_fcfa=price, base_quantity=base, added_by=user)
    _consume_line(line, ticket, user)
    _refresh(ticket)
    check_low_stock(ticket.bar, product_bar)
    return line


@transaction.atomic
def void_line(line, user, reason):
    ticket = _lock(line.ticket)
    line = TicketLine.objects.select_for_update().select_related("product_bar").get(pk=line.pk)
    if line.is_void:
        raise SalesError("Cette ligne est déjà annulée.")
    if ticket.status not in EDITABLE:
        raise SalesError("Ce ticket n'est plus modifiable.")
    _return_line_stock(line, ticket, user, f"Annulation ligne {ticket.display_name} : {reason}")
    line.is_void, line.void_reason = True, reason
    line.save()
    _refresh(ticket)
    if ticket.amount_paid_fcfa > ticket.total_fcfa:
        raise SalesError("Le client a déjà payé plus que le nouveau total : remboursez d'abord la différence.")
    check_low_stock(ticket.bar, line.product_bar)
    return line


@transaction.atomic
def set_discount(ticket, amount, user):
    ticket = _lock(ticket)
    if ticket.status not in EDITABLE:
        raise SalesError("Ce ticket n'est plus modifiable.")
    ticket.recalc(save=False)
    if amount < 0 or amount > ticket.subtotal_fcfa:
        raise SalesError("La remise doit être comprise entre 0 et le sous-total.")
    ticket.discount_fcfa = amount
    _refresh(ticket)
    if ticket.amount_paid_fcfa > ticket.total_fcfa:
        raise SalesError("Le client a déjà payé plus que le nouveau total : remboursez d'abord la différence.")
    return ticket


@transaction.atomic
def request_payment(ticket):
    """Passe le ticket en « facture en attente » (le client a fini de consommer)."""
    ticket = _lock(ticket)
    if ticket.status != Status.OPEN:
        raise SalesError("Seul un ticket ouvert peut passer en attente de paiement.")
    if not ticket.lines.filter(is_void=False).exists():
        raise SalesError("Le ticket est vide.")
    ticket.status = Status.AWAITING_PAYMENT
    ticket.save(update_fields=["status", "updated_at"])
    return ticket


@transaction.atomic
def validate_qr_ticket(ticket, user):
    ticket = _lock(ticket)
    if ticket.status != Status.PENDING_VALIDATION:
        raise SalesError("Cette commande a déjà été traitée.")
    ticket.status, ticket.validated_by, ticket.validated_at = Status.OPEN, user, timezone.now()
    ticket.save(update_fields=["status", "validated_by", "validated_at", "updated_at"])
    for line in ticket.lines.select_related("product_bar").filter(is_void=False, stock_consumed=False):
        _consume_line(line, ticket, user)
        check_low_stock(ticket.bar, line.product_bar)
    _refresh(ticket)
    return ticket


# ------------------------------------------------------------------ paiements
@transaction.atomic
def add_payment(ticket, amount, method, user, reference="", paid_at=None):
    ticket = _lock(ticket)
    if ticket.status not in PAYABLE:
        raise SalesError("Ce ticket ne peut pas recevoir de paiement.")
    ticket.recalc(save=False)
    if amount <= 0:
        raise SalesError("Le montant doit être supérieur à 0.")
    if amount > ticket.balance_due_fcfa:
        raise SalesError(f"Le montant dépasse le reste à payer ({ticket.balance_due_fcfa} FCFA).")
    payment = Payment.objects.create(bar=ticket.bar, ticket=ticket, kind=Payment.Kind.PAYMENT, amount_fcfa=amount,
                                     method=method, received_by=user, reference=reference,
                                     paid_at=paid_at or timezone.now())
    _refresh(ticket)
    return payment


@transaction.atomic
def refund_payment(ticket, amount, method, user, justification):
    ticket = _lock(ticket)
    if ticket.status not in PAYABLE:
        raise SalesError("Ce ticket ne peut pas être remboursé.")
    ticket.recalc(save=False)
    if amount <= 0 or amount > ticket.amount_paid_fcfa:
        raise SalesError(f"Le remboursement doit être compris entre 1 et {ticket.amount_paid_fcfa} FCFA.")
    if not justification.strip():
        raise SalesError("Un motif est obligatoire pour un remboursement.")
    payment = Payment.objects.create(bar=ticket.bar, ticket=ticket, kind=Payment.Kind.REFUND, amount_fcfa=amount,
                                     method=method, received_by=user, justification=justification.strip())
    _refresh(ticket)
    return payment


# ------------------------------------------------------------------ clients / crédit
def customer_debt(customer):
    """Dette = somme des soldes restants des tickets finalisés du client."""
    r = Ticket.objects.filter(customer=customer, status=Status.FINALIZED).aggregate(
        t=Sum("total_fcfa"), p=Sum("amount_paid_fcfa"))
    return (r["t"] or 0) - (r["p"] or 0)


# ------------------------------------------------------------------ finalisation / annulation
@transaction.atomic
def finalize_ticket(ticket, user):
    ticket = _lock(ticket)
    if ticket.status not in (Status.OPEN, Status.AWAITING_PAYMENT, Status.PAID):
        raise SalesError("Ce ticket ne peut pas être finalisé.")
    if not ticket.lines.filter(is_void=False).exists():
        raise SalesError("Le ticket est vide : annulez-le plutôt.")
    ticket.recalc(save=False)
    due = ticket.balance_due_fcfa
    if due > 0:
        if not ticket.customer_id:
            raise SalesError(f"Reste à payer : {due} FCFA. Encaissez-le, ou associez un client identifié pour vendre à crédit.")
        if customer_debt(ticket.customer) + due > ticket.customer.credit_limit_fcfa:
            raise SalesError("Le plafond de crédit de ce client serait dépassé.")
    ticket.status, ticket.finalized_by, ticket.finalized_at = Status.FINALIZED, user, timezone.now()
    ticket.save(update_fields=["status", "finalized_by", "finalized_at", "updated_at"])
    return ticket


@transaction.atomic
def cancel_ticket(ticket, user, reason):
    ticket = _lock(ticket)
    if ticket.status in (Status.FINALIZED, Status.CANCELLED):
        raise SalesError("Ce ticket ne peut plus être annulé.")
    ticket.recalc(save=False)
    if ticket.amount_paid_fcfa > 0:
        raise SalesError("Des paiements existent : remboursez-les avant d'annuler.")
    for line in ticket.lines.select_related("product_bar").filter(is_void=False):
        _return_line_stock(line, ticket, user, f"Ticket annulé {ticket.display_name} : {reason}")
        line.is_void, line.void_reason = True, "Ticket annulé"
        line.save()
    ticket.status, ticket.cancelled_by, ticket.cancel_reason = Status.CANCELLED, user, reason
    ticket.recalc(save=False)
    ticket.save(update_fields=["status", "cancelled_by", "cancel_reason", "subtotal_fcfa", "total_fcfa",
                               "amount_paid_fcfa", "payment_status", "updated_at"])
    return ticket


# ------------------------------------------------------------------ rapport de ventes
def sales_report(bar, start, end):
    """Ventes d'une période : par produit (quantité, CA, coût, marge) + encaissements par moyen de paiement."""
    lines = (TicketLine.objects.filter(ticket__bar=bar, ticket__business_date__range=(start, end), is_void=False)
             .exclude(ticket__status__in=EXCLUDED_FROM_SALES))
    rows = list(lines.values("product_bar__product__name", "product_bar__product__category__name")
                .annotate(qty=Sum("base_quantity"), revenue=Sum("line_total_fcfa"), cogs=Sum("cogs_fcfa"))
                .order_by("product_bar__product__category__name", "product_bar__product__name"))
    for r in rows:
        r["revenue"], r["cogs"] = r["revenue"] or 0, r["cogs"] or ZERO
        r["margin"] = r["revenue"] - r["cogs"]
    discounts = (Ticket.objects.filter(bar=bar, business_date__range=(start, end))
                 .exclude(status__in=EXCLUDED_FROM_SALES).aggregate(d=Sum("discount_fcfa"))["d"] or 0)
    revenue = sum(r["revenue"] for r in rows)
    cogs = sum((r["cogs"] for r in rows), ZERO)
    signed = Case(When(kind=Payment.Kind.REFUND, then=-F("amount_fcfa")), default=F("amount_fcfa"),
                  output_field=BigIntegerField())
    by_method = list(Payment.objects.filter(bar=bar, ticket__business_date__range=(start, end))
                     .values("method").annotate(total=Sum(signed)).order_by("method"))
    labels = dict(PaymentMethod.choices)
    for m in by_method:
        m["label"] = labels.get(m["method"], m["method"])
    totals = {"gross": revenue, "discounts": discounts, "net": revenue - discounts, "cogs": cogs,
              "margin": revenue - discounts - cogs, "collected": sum(m["total"] or 0 for m in by_method)}
    return rows, by_method, totals


@transaction.atomic
def create_qr_order(bar, raw_lines, note="", client_name=""):
    """Crée un ticket « commande QR à valider ». Les prix viennent de la base, jamais du navigateur.
    Le stock n'est sorti qu'à la validation par le personnel (validate_qr_ticket)."""
    from catalog.models import ProductBar


    wanted = {}
    for item in raw_lines if isinstance(raw_lines, list) else []:
        try:
            pid, qty = int(item["id"]), int(item["qty"])
        except (KeyError, TypeError, ValueError):
            raise SalesError("Commande invalide.")
        if qty < 1:
            raise SalesError("Quantité invalide.")
        wanted[pid] = min(wanted.get(pid, 0) + qty, 99)
    if not wanted or len(wanted) > 40:
        raise SalesError("Votre commande est vide ou trop longue.")

    found = {pb.id: pb for pb in ProductBar.objects.filter(bar=bar, is_active=True, id__in=wanted)
             .select_related("product")}
    if len(found) != len(wanted):
        raise SalesError("Un des produits n'est plus disponible : rechargez la page.")

    ticket = open_ticket(bar, None, custom_name=client_name[:80], note=note.strip()[:255],
                         source=Ticket.Source.QR)
    for pid, qty in wanted.items():
        pb = found[pid]
        TicketLine.objects.create(ticket=ticket, product_bar=pb, quantity=qty,
                                  unit_price_fcfa=pb.sale_price_fcfa, base_quantity=qty)
    ticket.recalc()
    return ticket