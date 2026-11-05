from datetime import date
from decimal import Decimal

from django.apps import apps
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import bar_required
from accounts.permissions import Perm
from catalog.models import Category, ProductBar
from core.models import PeriodType

from .forms import (AdjustmentForm, ClosingForm, CountCreateForm, CountEntryForm, LossForm,
                    OpeningStockForm, ReportForm)
from .models import DailyClosing, InventoryCount, LossReport, StockLot, StockMovement
from .services import (InsufficientStock, InventoryError, add_stock, apply_count, approve_loss,
                       cash_expected, check_low_stock, close_day, consume_stock, create_count,
                       date_to_datetime, movement_report, open_tickets_count, period_bounds,
                       reject_loss, save_count_entries, stock_by_product)

Kind = StockMovement.Kind
COUNT_ROLES = (Perm.STOCK_ADJUST, Perm.STOCK_RECEIVE)      # compter : gérant OU magasinier
CLOSING_ROLES = (Perm.POS_FINALIZE, Perm.STOCK_ADJUST)     # clôturer : caissier OU gérant
LOSS_ROLES = (Perm.LOSS_DECLARE, Perm.LOSS_APPROVE)
ZERO = Decimal("0")


def _form_page(request, form, title, back_url, back_args=None, submit="Enregistrer", subtitle="", multipart=False):
    return render(request, "inventory/form.html", {
        "form": form, "title": title, "back_url": back_url, "back_args": back_args or [],
        "submit": submit, "subtitle": subtitle, "multipart": multipart})


def _can_costs(membership):
    return membership.has_perm(Perm.REPORT_VIEW)


# ================================================================== stock
@bar_required(Perm.STOCK_VIEW)
def stock_list(request):
    bar, m = request.bar, request.membership
    stock = stock_by_product(bar)
    qs = ProductBar.objects.filter(bar=bar, is_active=True).select_related("product__category")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(product__name__icontains=q) | Q(product__brand__icontains=q))
    category = request.GET.get("category", "")
    if category.isdigit():
        qs = qs.filter(product__category_id=int(category))
    state = request.GET.get("state", "")
    rows = []
    for pb in qs.order_by("product__category__name", "product__name"):
        s = stock.get(pb.id, {"qty": ZERO, "value": ZERO, "lots": 0})
        row = {"pb": pb, "qty": s["qty"], "value": s["value"], "lots": s["lots"],
               "low": s["qty"] <= pb.low_stock_threshold, "out": s["qty"] <= 0}
        if state == "bas" and not row["low"]:
            continue
        if state == "rupture" and not row["out"]:
            continue
        rows.append(row)
    can_costs = _can_costs(m)
    return render(request, "inventory/stock_list.html", {
        "rows": rows, "q": q, "category": category, "state": state, "can_costs": can_costs,
        "total_value": sum((r["value"] for r in rows), ZERO) if can_costs else None,
        "categories": Category.objects.filter(products__bar_products__bar=bar).distinct().order_by("name"),
        "can_adjust": m.has_perm(Perm.STOCK_ADJUST)})


@bar_required(Perm.STOCK_VIEW)
def stock_product(request, pk):
    pb = get_object_or_404(ProductBar.objects.select_related("product__category"), pk=pk, bar=request.bar)
    s = stock_by_product(request.bar).get(pb.id, {"qty": ZERO, "value": ZERO, "lots": 0})
    return render(request, "inventory/stock_product.html", {
        "pb": pb, "qty": s["qty"], "value": s["value"] if _can_costs(request.membership) else None,
        "lots": list(pb.lots.filter(status=StockLot.Status.OPEN, remaining_qty__gt=0)),
        "movements": list(pb.movements.select_related("created_by", "lot")[:30]),
        "can_costs": _can_costs(request.membership),
        "can_adjust": request.membership.has_perm(Perm.STOCK_ADJUST)})


@bar_required(Perm.STOCK_VIEW)
def movement_list(request):
    qs = StockMovement.objects.filter(bar=request.bar).select_related("product_bar__product", "created_by")
    product = request.GET.get("product", "")
    if product.isdigit():
        qs = qs.filter(product_bar_id=int(product))
    kind = request.GET.get("kind", "")
    if kind in Kind.values:
        qs = qs.filter(kind=kind)
    for param, lookup in (("from", "business_date__gte"), ("to", "business_date__lte")):
        try:
            qs = qs.filter(**{lookup: date.fromisoformat(request.GET.get(param, ""))})
        except ValueError:
            pass                                            # date absente ou invalide : on ignore le filtre
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "inventory/movement_list.html", {
        "page": page, "kinds": Kind.choices, "kind": kind, "product": product,
        "querystring": params.urlencode(), "can_costs": _can_costs(request.membership),
        "products": ProductBar.objects.filter(bar=request.bar).select_related("product")})


@bar_required(Perm.STOCK_ADJUST, write=True)
def opening_stock(request):
    form = OpeningStockForm(request.POST or None, bar=request.bar)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        pb = d["product_bar"]
        cost = d["unit_cost_fcfa"] if d["unit_cost_fcfa"] is not None else pb.purchase_price_fcfa
        add_stock(bar=request.bar, product_bar=pb, qty=d["quantity"], unit_cost=cost, kind=Kind.OPENING,
                  source=StockLot.Source.OPENING, user=request.user, note="Stock initial",
                  received_at=date_to_datetime(d["since"]))
        messages.success(request, f"Stock initial enregistré pour « {pb.product} ».")
        return redirect("inventory:stock_product", pk=pb.pk)
    return _form_page(request, form, "Stock initial", "inventory:stock_list", submit="Enregistrer",
                      subtitle="Pour le stock que vous aviez déjà avant d'utiliser l'application.")


@bar_required(Perm.STOCK_ADJUST, write=True)
def adjust_stock(request):
    form = AdjustmentForm(request.POST or None, bar=request.bar)
    if request.method == "POST" and form.is_valid():
        d, pb = form.cleaned_data, form.cleaned_data["product_bar"]
        try:
            with transaction.atomic():
                if d["direction"] == "OUT":
                    consume_stock(bar=request.bar, product_bar=pb, qty=d["quantity"], kind=Kind.ADJUST_OUT,
                                  user=request.user, note=d["note"])
                else:
                    cost = d["unit_cost_fcfa"] if d["unit_cost_fcfa"] is not None else pb.purchase_price_fcfa
                    add_stock(bar=request.bar, product_bar=pb, qty=d["quantity"], unit_cost=cost,
                              kind=Kind.ADJUST_IN, source=StockLot.Source.ADJUSTMENT,
                              user=request.user, note=d["note"])
        except InsufficientStock as exc:
            form.add_error("quantity", str(exc))
        else:
            check_low_stock(request.bar, pb)
            messages.success(request, "Ajustement enregistré dans le journal des mouvements.")
            return redirect("inventory:stock_product", pk=pb.pk)
    return _form_page(request, form, "Ajustement du stock", "inventory:stock_list", submit="Enregistrer l'ajustement",
                      subtitle="Pour corriger un écart. Pour compter tout le stock, utilisez plutôt un inventaire.")


# ================================================================== pertes
@bar_required(LOSS_ROLES)
def loss_list(request):
    m = request.membership
    can_review = m.has_perm(Perm.LOSS_APPROVE)
    qs = LossReport.objects.filter(bar=request.bar).select_related("product_bar__product", "declared_by", "reviewed_by")
    if not can_review:
        qs = qs.filter(declared_by=request.user)        # un déclarant ne voit que ses propres pertes
    state = request.GET.get("state", "")
    if state in LossReport.Status.values:
        qs = qs.filter(status=state)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    pending = LossReport.objects.filter(bar=request.bar, status=LossReport.Status.PENDING).count() if can_review else None
    return render(request, "inventory/loss_list.html", {
        "page": page, "state": state, "can_review": can_review, "pending": pending,
        "can_declare": m.has_perm(Perm.LOSS_DECLARE), "statuses": LossReport.Status.choices})


@bar_required(Perm.LOSS_DECLARE, write=True)
def loss_create(request):
    form = LossForm(request.POST or None, request.FILES or None, bar=request.bar)
    if request.method == "POST" and form.is_valid():
        report = form.save(commit=False)
        report.bar, report.declared_by = request.bar, request.user
        report.business_date = request.bar.current_business_date()
        report.save()
        _notify_loss(request, report)
        messages.success(request, "Perte déclarée : le gérant doit la valider pour que le stock soit mis à jour.")
        return redirect("inventory:loss_list")
    return _form_page(request, form, "Déclarer une perte", "inventory:loss_list", submit="Déclarer",
                      subtitle="Bouteille cassée, produit périmé, offert… Le stock sera ajusté après validation.",
                      multipart=True)


def _notify_loss(request, report):
    if not apps.is_installed("notifications"):
        return
    from notifications.models import Notification, NotificationType
    from notifications.services import notify_bar
    notify_bar(request.bar, type=NotificationType.LOSS_DECLARED, perm=Perm.LOSS_APPROVE,
               exclude_user=request.user, level=Notification.Level.WARNING, url="/stock/pertes/",
               title=f"Perte à valider : {report.quantity.normalize():f} × {report.product_bar.product}",
               body=f"{report.get_reason_display()} · déclarée par {request.user}")


def _review(request, pk, approve):
    report = get_object_or_404(LossReport.objects.select_related("product_bar__product"), pk=pk, bar=request.bar)
    if report.declared_by_id == request.user.id and not request.membership.is_owner:
        messages.error(request, "Vous ne pouvez pas valider votre propre déclaration.")
        return redirect("inventory:loss_list")
    try:
        if approve:
            approve_loss(report, request.user)
            messages.success(request, "Perte validée : le stock a été mis à jour.")
        else:
            reject_loss(report, request.user)
            messages.info(request, "Perte rejetée : le stock n'a pas été modifié.")
    except InsufficientStock:
        messages.error(request, "Stock insuffisant pour enregistrer cette perte : régularisez d'abord le stock "
                                "(réception, stock initial ou ajustement).")
    except InventoryError as exc:
        messages.error(request, str(exc))
    else:
        if apps.is_installed("notifications") and report.declared_by_id and report.declared_by_id != request.user.id:
            from notifications.models import NotificationType
            from notifications.services import notify
            notify(recipient=report.declared_by, bar=request.bar, type=NotificationType.LOSS_REVIEWED,
                   title=f"Votre perte a été {'validée' if approve else 'rejetée'}",
                   body=f"{report.quantity.normalize():f} × {report.product_bar.product}", url="/stock/pertes/")
    return redirect("inventory:loss_list")


@require_POST
@bar_required(Perm.LOSS_APPROVE, write=True)
def loss_approve(request, pk):
    return _review(request, pk, approve=True)


@require_POST
@bar_required(Perm.LOSS_APPROVE, write=True)
def loss_reject(request, pk):
    return _review(request, pk, approve=False)


# ================================================================== inventaires physiques
@bar_required(COUNT_ROLES)
def count_list(request):
    qs = InventoryCount.objects.filter(bar=request.bar).select_related("counted_by", "validated_by")
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "inventory/count_list.html", {
        "page": page, "can_validate": request.membership.has_perm(Perm.STOCK_ADJUST)})


@bar_required(COUNT_ROLES, write=True)
def count_create(request):
    form = CountCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        count = create_count(request.bar, d["period_type"], d["reference_date"], request.user, d["note"])
        messages.success(request, "Inventaire créé : saisissez les quantités comptées.")
        return redirect("inventory:count_detail", pk=count.pk)
    return _form_page(request, form, "Nouvel inventaire", "inventory:count_list", submit="Commencer le comptage",
                      subtitle="Comptez de préférence quand le bar est calme (à la fermeture).")


@bar_required(COUNT_ROLES, write=True)
def count_detail(request, pk):
    count = get_object_or_404(InventoryCount, pk=pk, bar=request.bar)
    editable = count.status != InventoryCount.Status.VALIDATED
    form = CountEntryForm(request.POST or None, count=count)
    if request.method == "POST" and editable and form.is_valid():
        save_count_entries(count, form.entries())
        messages.success(request, "Comptage enregistré.")
        return redirect("inventory:count_detail", pk=count.pk)
    lines = list(count.lines.select_related("product_bar__product"))
    can_costs = _can_costs(request.membership)
    return render(request, "inventory/count_detail.html", {
        "count": count, "form": form, "editable": editable, "lines": lines,
        "counted": sum(1 for l in lines if l.counted_qty is not None), "total": len(lines),
        "can_costs": can_costs,
        "gap_value": sum((l.difference_value_fcfa for l in lines if l.counted_qty is not None), ZERO) if can_costs else None,
        "can_validate": editable and request.membership.has_perm(Perm.STOCK_ADJUST)})


@require_POST
@bar_required(Perm.STOCK_ADJUST, write=True)
def count_validate(request, pk):
    count = get_object_or_404(InventoryCount, pk=pk, bar=request.bar)
    try:
        gaps = apply_count(count, request.user)
    except InventoryError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Inventaire validé : {gaps} écart(s) régularisé(s) dans le stock." if gaps
                         else "Inventaire validé : aucun écart, le stock est exact.")
        if gaps:
            _notify_gaps(request, count, gaps)
    return redirect("inventory:count_detail", pk=count.pk)


def _notify_gaps(request, count, gaps):
    if not apps.is_installed("notifications"):
        return
    from notifications.models import Notification, NotificationType
    from notifications.services import notify_bar
    notify_bar(request.bar, type=NotificationType.INVENTORY_GAP, perm=Perm.REPORT_VIEW,
               exclude_user=request.user, level=Notification.Level.WARNING, url=f"/stock/inventaires/{count.pk}/",
               title=f"Inventaire du {count.period_end:%d/%m/%Y} : {gaps} écart(s) de stock")


@require_POST
@bar_required(Perm.STOCK_ADJUST, write=True)
def count_delete(request, pk):
    count = get_object_or_404(InventoryCount, pk=pk, bar=request.bar)
    if count.status == InventoryCount.Status.VALIDATED:
        messages.error(request, "Un inventaire validé est conservé : il ne peut pas être supprimé.")
        return redirect("inventory:count_detail", pk=count.pk)
    count.delete()
    messages.success(request, "Inventaire supprimé.")
    return redirect("inventory:count_list")


# ================================================================== rapport par période
@bar_required(Perm.REPORT_VIEW)
def inventory_report(request):
    bar = request.bar
    form = ReportForm(request.GET)          # toujours lié : tous les champs sont facultatifs
    form.is_valid()
    period = form.cleaned_data.get("period") or PeriodType.DAY
    ref = form.cleaned_data.get("date") or bar.current_business_date()
    start, end = period_bounds(period, ref)
    rows, totals = movement_report(bar, start, end)
    return render(request, "inventory/report.html", {
        "form": form, "period": period, "start": start, "end": end, "rows": rows, "totals": totals,
        "periods": PeriodType.choices})


# ================================================================== clôtures journalières
@bar_required(CLOSING_ROLES)
def closing_list(request):
    qs = DailyClosing.objects.filter(bar=request.bar).select_related("closed_by")
    page = Paginator(qs, 31).get_page(request.GET.get("page"))
    today = request.bar.current_business_date()
    return render(request, "inventory/closing_list.html", {
        "page": page, "today": today,
        "today_closed": DailyClosing.objects.filter(bar=request.bar, business_date=today).exists()})


@bar_required(CLOSING_ROLES, write=True)
def closing_close(request):
    bar = request.bar
    day = bar.current_business_date()
    date_param = request.GET.get("date") or request.POST.get("date")
    if date_param:
        try:
            candidate = date.fromisoformat(date_param)
        except ValueError:
            candidate = None
        if candidate and candidate <= day:
            day = candidate
    if DailyClosing.objects.filter(bar=bar, business_date=day).exists():
        messages.info(request, "Cette journée est déjà clôturée.")
        return redirect("inventory:closing_list")
    form = ClosingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            closing = close_day(bar, day, request.user, form.cleaned_data["cash_counted_fcfa"], form.cleaned_data["note"])
        except InventoryError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Journée du {day:%d/%m/%Y} clôturée.")
            return redirect("inventory:closing_detail", pk=closing.pk)
    report, _ = movement_report(bar, day, day)
    return render(request, "inventory/closing_close.html", {
        "form": form, "day": day, "report": report, "cash_expected": cash_expected(bar, day),
        "open_tickets": open_tickets_count(bar, day)})


@bar_required(CLOSING_ROLES)
def closing_detail(request, pk):
    closing = get_object_or_404(DailyClosing.objects.select_related("closed_by"), pk=pk, bar=request.bar)
    lines = list(closing.lines.select_related("product_bar__product"))
    diff = None
    if closing.cash_counted_fcfa is not None:
        diff = closing.cash_counted_fcfa - closing.cash_expected_fcfa
    return render(request, "inventory/closing_detail.html", {
        "closing": closing, "lines": lines, "cash_diff": diff,
        "revenue": sum(l.revenue_fcfa for l in lines), "cogs": sum(l.cogs_fcfa for l in lines)})