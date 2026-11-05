from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import bar_required
from accounts.permissions import Perm

from .forms import LineForm, OrderForm, PaymentForm, ReceiveForm, SupplierForm
from .models import PurchaseOrder, PurchaseOrderLine, Supplier, SupplierPayment
from .services import (ReceptionError, audit, fully_received, has_receptions,
                       notify_purchasers, receive_order, refresh_order_status)

Status = PurchaseOrder.Status
ORDER_ROLES = (Perm.PURCHASE_MANAGE, Perm.STOCK_RECEIVE)     # voir les commandes : acheteur OU magasinier
NOT_DEBT = (Status.DRAFT, Status.CANCELLED)


def _form_page(request, form, title, back_url, back_args=None, submit="Enregistrer", subtitle=""):
    return render(request, "purchasing/form.html", {
        "form": form, "title": title, "back_url": back_url, "back_args": back_args or [],
        "submit": submit, "subtitle": subtitle})


def _order(request, pk):
    return get_object_or_404(PurchaseOrder.objects.select_related("supplier"), pk=pk, bar=request.bar)


# ================================================================== fournisseurs
@bar_required(Perm.PURCHASE_MANAGE)
def supplier_list(request):
    bar = request.bar
    qs = Supplier.objects.filter(bar=bar)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(contact_name__icontains=q) | Q(phone__icontains=q))
    state = request.GET.get("state", "actifs")
    if state == "actifs":
        qs = qs.filter(is_active=True)
    elif state == "inactifs":
        qs = qs.filter(is_active=False)
    suppliers = list(qs)
    rows = (PurchaseOrder.objects.filter(bar=bar).exclude(status__in=NOT_DEBT)
            .values("supplier_id").annotate(t=Sum("total_fcfa"), p=Sum("amount_paid_fcfa")).order_by())
    debt = {r["supplier_id"]: (r["t"] or 0) - (r["p"] or 0) for r in rows}
    for s in suppliers:
        s.debt = debt.get(s.id, 0)
    return render(request, "purchasing/supplier_list.html", {"suppliers": suppliers, "q": q, "state": state})


@bar_required(Perm.PURCHASE_MANAGE, write=True)
def supplier_add(request):
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        supplier = form.save(commit=False)
        supplier.bar = request.bar
        supplier.save()
        messages.success(request, f"Fournisseur « {supplier} » ajouté.")
        return redirect("purchasing:supplier_detail", pk=supplier.pk)
    return _form_page(request, form, "Nouveau fournisseur", "purchasing:supplier_list", submit="Ajouter")


@bar_required(Perm.PURCHASE_MANAGE)
def supplier_detail(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk, bar=request.bar)
    orders = list(supplier.orders.all()[:20])
    agg = supplier.orders.exclude(status__in=NOT_DEBT).aggregate(t=Sum("total_fcfa"), p=Sum("amount_paid_fcfa"))
    return render(request, "purchasing/supplier_detail.html", {
        "supplier": supplier, "orders": orders,
        "billed": agg["t"] or 0, "paid": agg["p"] or 0, "debt": (agg["t"] or 0) - (agg["p"] or 0)})


@bar_required(Perm.PURCHASE_MANAGE, write=True)
def supplier_edit(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk, bar=request.bar)
    form = SupplierForm(request.POST or None, instance=supplier, show_active=True)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Fournisseur mis à jour.")
        return redirect("purchasing:supplier_detail", pk=supplier.pk)
    return _form_page(request, form, f"Modifier : {supplier}", "purchasing:supplier_detail", [supplier.pk])


@require_POST
@bar_required(Perm.PURCHASE_MANAGE, write=True)
def supplier_toggle(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk, bar=request.bar)
    supplier.is_active = not supplier.is_active
    supplier.save(update_fields=["is_active", "updated_at"])
    messages.success(request, "Fournisseur réactivé." if supplier.is_active else "Fournisseur désactivé.")
    return redirect("purchasing:supplier_detail", pk=supplier.pk)


# ================================================================== commandes
@bar_required(ORDER_ROLES)
def order_list(request):
    bar, m = request.bar, request.membership
    today = bar.current_business_date()
    can_money = m.has_perm(Perm.PURCHASE_MANAGE)
    qs = PurchaseOrder.objects.filter(bar=bar).select_related("supplier")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(reference__icontains=q) | Q(supplier__name__icontains=q))
    state = request.GET.get("state", "")
    debt_q = ~Q(status__in=NOT_DEBT) & ~Q(payment_status=PurchaseOrder.PaymentStatus.PAID)
    if state == "brouillons":
        qs = qs.filter(status=Status.DRAFT)
    elif state == "a_recevoir":
        qs = qs.filter(status__in=(Status.SENT, Status.PARTIAL))
    elif state == "a_payer" and can_money:
        qs = qs.filter(debt_q)
    elif state == "retard" and can_money:
        qs = qs.filter(debt_q, due_date__lt=today)
    elif state == "terminees":
        qs = qs.filter(status=Status.CLOSED)
    elif state == "annulees":
        qs = qs.filter(status=Status.CANCELLED)
    else:
        state = ""
        qs = qs.exclude(status=Status.CANCELLED)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)

    summary = None
    if can_money:
        owed = PurchaseOrder.objects.filter(bar=bar).filter(debt_q)
        agg = owed.aggregate(t=Sum("total_fcfa"), p=Sum("amount_paid_fcfa"))
        summary = {"debt": (agg["t"] or 0) - (agg["p"] or 0), "count": owed.count(),
                   "overdue": owed.filter(due_date__lt=today).count()}
    to_receive = PurchaseOrder.objects.filter(bar=bar, status__in=(Status.SENT, Status.PARTIAL)).count()
    return render(request, "purchasing/order_list.html", {
        "page": page, "q": q, "state": state, "querystring": params.urlencode(),
        "summary": summary, "to_receive": to_receive, "can_money": can_money, "today": today})


@bar_required(Perm.PURCHASE_MANAGE, write=True)
def order_create(request):
    if not Supplier.objects.filter(bar=request.bar, is_active=True).exists():
        messages.info(request, "Ajoutez d'abord un fournisseur avant de passer une commande.")
        return redirect("purchasing:supplier_add")
    form = OrderForm(request.POST or None, bar=request.bar)
    if request.method == "POST" and form.is_valid():
        order = form.save(commit=False)
        order.bar, order.created_by = request.bar, request.user
        order.save()
        messages.success(request, "Commande créée en brouillon : ajoutez maintenant les produits.")
        return redirect("purchasing:order_detail", pk=order.pk)
    return _form_page(request, form, "Nouvelle commande fournisseur", "purchasing:order_list", submit="Créer la commande")


@bar_required(ORDER_ROLES)
def order_detail(request, pk):
    order = _order(request, pk)
    m = request.membership
    can_manage, can_receive = m.has_perm(Perm.PURCHASE_MANAGE), m.has_perm(Perm.STOCK_RECEIVE)
    lines = list(order.lines.select_related("product_bar__product"))
    for l in lines:
        l.remaining = l.quantity_packages - l.received_packages
        l.units_total = l.quantity_packages * l.units_per_package
    received_any = any(l.received_packages for l in lines)
    st = order.status
    return render(request, "purchasing/order_detail.html", {
        "order": order, "lines": lines, "payments": list(order.payments.select_related("paid_by")),
        "can_money": can_manage, "can_manage": can_manage, "can_receive": can_receive,
        "today": request.bar.current_business_date(),
        "editable": st == Status.DRAFT,
        "can_send": st == Status.DRAFT and bool(lines),
        "can_receive_now": st in (Status.SENT, Status.PARTIAL),
        "can_pay": st in (Status.SENT, Status.PARTIAL, Status.RECEIVED, Status.CLOSED) and order.balance_due_fcfa > 0,
        "can_cancel": st in (Status.DRAFT, Status.SENT) and not received_any and not order.payments.exists(),
        "can_close": st in (Status.PARTIAL, Status.RECEIVED),
        "can_edit_header": st not in (Status.CANCELLED, Status.CLOSED),
    })


@bar_required(Perm.PURCHASE_MANAGE, write=True)
def order_edit(request, pk):
    order = _order(request, pk)
    if order.status in (Status.CANCELLED, Status.CLOSED):
        messages.error(request, "Cette commande est terminée : elle ne peut plus être modifiée.")
        return redirect("purchasing:order_detail", pk=order.pk)
    form = OrderForm(request.POST or None, instance=order, bar=request.bar)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Commande mise à jour.")
        return redirect("purchasing:order_detail", pk=order.pk)
    return _form_page(request, form, f"Modifier {order.reference}", "purchasing:order_detail", [order.pk])


# ------------------------------------------------------------------ lignes (brouillon uniquement)
def _draft_or_redirect(request, order):
    if order.status != Status.DRAFT:
        messages.error(request, "Les produits ne se modifient plus une fois la commande envoyée.")
        return redirect("purchasing:order_detail", pk=order.pk)
    return None


@bar_required(Perm.PURCHASE_MANAGE, write=True)
def line_add(request, pk):
    order = _order(request, pk)
    blocked = _draft_or_redirect(request, order)
    if blocked:
        return blocked
    form = LineForm(request.POST or None, bar=request.bar, order=order)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            line = form.save(commit=False)
            line.order = order
            line.save()
            order.recalc()
        messages.success(request, "Produit ajouté à la commande.")
        return redirect("purchasing:order_detail", pk=order.pk)
    return _form_page(request, form, f"Ajouter un produit à {order.reference}", "purchasing:order_detail",
                      [order.pk], submit="Ajouter")


@bar_required(Perm.PURCHASE_MANAGE, write=True)
def line_edit(request, pk):
    line = get_object_or_404(PurchaseOrderLine.objects.select_related("order__supplier", "product_bar__product"),
                             pk=pk, order__bar=request.bar)
    blocked = _draft_or_redirect(request, line.order)
    if blocked:
        return blocked
    form = LineForm(request.POST or None, instance=line, bar=request.bar, order=line.order)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            line.order.recalc()
        messages.success(request, "Ligne mise à jour.")
        return redirect("purchasing:order_detail", pk=line.order_id)
    return _form_page(request, form, f"Modifier : {line.product_bar.product}", "purchasing:order_detail", [line.order_id])


@require_POST
@bar_required(Perm.PURCHASE_MANAGE, write=True)
def line_delete(request, pk):
    line = get_object_or_404(PurchaseOrderLine.objects.select_related("order"), pk=pk, order__bar=request.bar)
    order = line.order
    blocked = _draft_or_redirect(request, order)
    if blocked:
        return blocked
    with transaction.atomic():
        line.delete()
        order.recalc()
    messages.success(request, "Ligne supprimée.")
    return redirect("purchasing:order_detail", pk=order.pk)


# ------------------------------------------------------------------ changements d'état
@require_POST
@bar_required(Perm.PURCHASE_MANAGE, write=True)
def order_send(request, pk):
    order = _order(request, pk)
    if order.status != Status.DRAFT:
        messages.error(request, "Cette commande a déjà été envoyée.")
    elif not order.lines.exists() or order.total_fcfa <= 0:
        messages.error(request, "Ajoutez au moins un produit avant d'envoyer la commande.")
    else:
        order.status = Status.SENT
        order.save(update_fields=["status", "updated_at"])
        messages.success(request, "Commande envoyée au fournisseur. Réceptionnez-la à la livraison.")
    return redirect("purchasing:order_detail", pk=order.pk)


@require_POST
@bar_required(Perm.PURCHASE_MANAGE, write=True)
def order_cancel(request, pk):
    order = _order(request, pk)
    if order.status not in (Status.DRAFT, Status.SENT) or has_receptions(order):
        messages.error(request, "Une commande déjà (en partie) réceptionnée ne peut pas être annulée.")
    elif order.payments.exists():
        messages.error(request, "Des paiements sont enregistrés : supprimez-les d'abord (remboursement du fournisseur).")
    else:
        order.status = Status.CANCELLED
        order.save(update_fields=["status", "updated_at"])
        audit(request, "purchase.cancelled", order, reference=order.reference)
        messages.success(request, "Commande annulée.")
    return redirect("purchasing:order_detail", pk=order.pk)


@require_POST
@bar_required(Perm.PURCHASE_MANAGE, write=True)
def order_close(request, pk):
    """Clôture une commande dont le reste ne sera pas livré (livraison partielle définitive)."""
    order = _order(request, pk)
    if order.status in (Status.PARTIAL, Status.RECEIVED):
        order.status = Status.CLOSED
        order.save(update_fields=["status", "updated_at"])
        audit(request, "purchase.closed", order, reference=order.reference, fully_received=fully_received(order))
        messages.success(request, "Commande clôturée.")
    else:
        messages.error(request, "Cette commande ne peut pas être clôturée.")
    return redirect("purchasing:order_detail", pk=order.pk)


# ------------------------------------------------------------------ réception du stock
@bar_required(Perm.STOCK_RECEIVE, write=True)
def order_receive(request, pk):
    order = _order(request, pk)
    if order.status not in (Status.SENT, Status.PARTIAL):
        messages.error(request, "Cette commande n'est pas en attente de réception.")
        return redirect("purchasing:order_detail", pk=order.pk)
    form = ReceiveForm(request.POST or None, order=order)
    if request.method == "POST" and form.is_valid():
        try:
            order = receive_order(order, form.quantities, request.user)
        except ReceptionError as exc:
            messages.error(request, str(exc))
        else:
            done = order.status == Status.RECEIVED
            messages.success(request, "Commande entièrement reçue : le stock est à jour." if done
                             else "Réception partielle enregistrée : le stock est à jour.")
            notify_purchasers(order, f"Commande {order.reference} {'reçue' if done else 'reçue en partie'}",
                              exclude_user=request.user)
            return redirect("purchasing:order_detail", pk=order.pk)
    return render(request, "purchasing/receive.html", {"form": form, "order": order})


# ------------------------------------------------------------------ paiements fournisseur
@bar_required(Perm.PURCHASE_MANAGE, write=True)
def payment_add(request, pk):
    order = _order(request, pk)
    if order.status in (Status.DRAFT, Status.CANCELLED) or order.balance_due_fcfa <= 0:
        messages.error(request, "Aucun paiement à enregistrer pour cette commande.")
        return redirect("purchasing:order_detail", pk=order.pk)
    form = PaymentForm(request.POST or None, order=order)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            payment = form.save(commit=False)
            payment.bar, payment.order, payment.paid_by = request.bar, order, request.user
            payment.save()
            order.recalc()
            refresh_order_status(order)
        messages.success(request, "Paiement enregistré." if order.balance_due_fcfa
                         else "Paiement enregistré : la commande est soldée.")
        return redirect("purchasing:order_detail", pk=order.pk)
    return _form_page(request, form, f"Paiement : {order.reference}", "purchasing:order_detail", [order.pk],
                      submit="Enregistrer le paiement",
                      subtitle=f"Reste à payer : {order.balance_due_fcfa} FCFA")


@require_POST
@bar_required(Perm.PURCHASE_MANAGE, write=True)
def payment_delete(request, pk):
    payment = get_object_or_404(SupplierPayment.objects.select_related("order"), pk=pk, bar=request.bar)
    order = payment.order
    with transaction.atomic():
        audit(request, "purchase.payment_deleted", payment, order=order.reference,
              amount=payment.amount_fcfa, method=payment.method, reference=payment.reference)
        payment.delete()
        order.recalc()
        refresh_order_status(order)
    messages.success(request, "Paiement supprimé (l'opération est conservée dans le journal d'audit).")
    return redirect("purchasing:order_detail", pk=order.pk)