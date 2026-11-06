from datetime import date

from django.apps import apps
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import bar_required
from accounts.permissions import Perm
from core.models import PeriodType
from inventory.forms import ReportForm
from inventory.services import period_bounds

from sales.forms import (CancelForm, CustomerForm, DiscountForm, LineForm, PaymentForm, RefundForm,TicketCreateForm, VoidLineForm)
from sales.models import Customer, Ticket, TicketLine
from sales.services import (EDITABLE, SalesError, add_line, add_payment, cancel_ticket, customer_debt,
                       finalize_ticket, open_ticket, refund_payment, request_payment, sales_report,
                       set_discount, validate_qr_ticket, void_line)

Status = Ticket.Status
SELL_ROLES = (Perm.POS_SELL, Perm.POS_FINALIZE)        # voir les tickets : vendeuse OU caissier
CUSTOMER_ROLES = (Perm.CREDIT_MANAGE,)                 # clients et crédits : caissier / gérant


def _form_page(request, form, title, back_url, back_args=None, submit="Enregistrer", subtitle="", multipart=False):
    return render(request, "sales/form.html", {
        "form": form, "title": title, "back_url": back_url, "back_args": back_args or [],
        "submit": submit, "subtitle": subtitle, "multipart": multipart})


def _can_costs(membership):
    return membership.has_perm(Perm.REPORT_VIEW)


def _ticket(request, pk):
    return get_object_or_404(Ticket.objects.select_related("customer"), pk=pk, bar=request.bar)


def _flash_errors(request, form):
    for errors in form.errors.values():
        for err in errors:
            messages.error(request, err)


def _act(request, pk, action, success, after=None):
    """Exécute une action de service sur un ticket, puis revient à sa fiche."""
    ticket = _ticket(request, pk)
    try:
        action(ticket)
    except SalesError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, success)
        if after:
            after(ticket)
    return redirect("sales:ticket_detail", pk=ticket.pk)


# ------------------------------------------------------------------ notifications
def _notify_paid(request, ticket):
    """Prévient la vendeuse qui a ouvert le ticket qu'il est entièrement payé."""
    ticket.refresh_from_db()
    if not apps.is_installed("notifications"):
        return
    if ticket.payment_status != Ticket.PaymentStatus.PAID or not ticket.opened_by_id:
        return
    if ticket.opened_by_id == request.user.id:
        return
    from notifications.models import Notification, NotificationType
    from notifications.services import notify
    notify(recipient=ticket.opened_by, bar=request.bar, type=NotificationType.TICKET_PAID,
           level=Notification.Level.SUCCESS, url=f"/sales/tickets/{ticket.pk}/",
           title=f"Ticket {ticket.display_name} payé",
           body=f"{ticket.total_fcfa} FCFA encaissés par {request.user}",
           dedup_key=f"ticket-paid:{ticket.pk}")


def _notify_payment(request, ticket, amount):
    """Prévient les responsables des rapports d'un encaissement important sur une dette client."""
    if not apps.is_installed("notifications") or ticket.status != Status.FINALIZED:
        return
    from notifications.models import NotificationType
    from notifications.services import notify_bar
    notify_bar(request.bar, type=NotificationType.PAYMENT_RECEIVED, perm=Perm.CREDIT_MANAGE,
               exclude_user=request.user, url=f"/sales/tickets/{ticket.pk}/",
               title=f"Paiement reçu : {amount} FCFA ({ticket.customer or ticket.display_name})",
               body=f"Reste à payer : {ticket.balance_due_fcfa} FCFA")


# ================================================================== tickets
@bar_required(SELL_ROLES)
def ticket_list(request):
    bar, m = request.bar, request.membership
    day = bar.current_business_date()
    try:
        day = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        pass                                                # date absente ou invalide : jour courant
    qs = Ticket.objects.filter(bar=bar, business_date=day).select_related("customer", "opened_by")
    state = request.GET.get("state", "")
    if state in Status.values:
        qs = qs.filter(status=state)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(label__icontains=q) | Q(custom_name__icontains=q) | Q(table_label__icontains=q))
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    totals = (Ticket.objects.filter(bar=bar, business_date=day)
              .exclude(status__in=(Status.CANCELLED, Status.PENDING_VALIDATION))
              .aggregate(total=Sum("total_fcfa"), paid=Sum("amount_paid_fcfa")))
    return render(request, "sales/ticket_list.html", {
        "page": page, "day": day, "state": state, "q": q, "statuses": Status.choices,
        "day_total": totals["total"] or 0, "day_paid": totals["paid"] or 0,
        "pending_qr": Ticket.objects.filter(bar=bar, status=Status.PENDING_VALIDATION).count(),
        "can_sell": m.has_perm(Perm.POS_SELL), "can_validate": m.has_perm(Perm.POS_VALIDATE_QR)})


@bar_required(Perm.POS_SELL, write=True)
def ticket_create(request):
    form = TicketCreateForm(request.POST or None, bar=request.bar)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        ticket = open_ticket(request.bar, request.user, custom_name=d["custom_name"], customer=d["customer"],
                             table_label=d["table_label"], note=d["note"], payment_timing=d["payment_timing"])
        messages.success(request, f"Ticket {ticket.display_name} ouvert.")
        return redirect("sales:ticket_detail", pk=ticket.pk)
    return _form_page(request, form, "Nouveau ticket", "sales:ticket_list", submit="Ouvrir le ticket",
                      subtitle="Le nom automatique (ClientA1, ClientA2…) est attribué à l'ouverture.")


@bar_required(SELL_ROLES)
def ticket_detail(request, pk):
    ticket, m = _ticket(request, pk), request.membership
    can_costs = _can_costs(m)
    can_sell = m.has_perm(Perm.POS_SELL)
    lines = list(ticket.lines.select_related("product_bar__product", "serving", "added_by"))
    editable = ticket.status in EDITABLE
    return render(request, "sales/ticket_detail.html", {
        "ticket": ticket, "lines": lines, "payments": list(ticket.payments.select_related("received_by")),
        "editable": editable, "can_costs": can_costs,
        "cogs": sum(l.cogs_fcfa for l in lines if not l.is_void) if can_costs else None,
        "line_form": LineForm(bar=request.bar) if editable and can_sell else None,
        "payment_form": PaymentForm(initial={"amount_fcfa": max(ticket.balance_due_fcfa, 0)}),
        "refund_form": RefundForm(), "void_form": VoidLineForm(), "cancel_form": CancelForm(),
        "discount_form": DiscountForm(initial={"discount_fcfa": ticket.discount_fcfa}),
        "can_sell": can_sell, "can_finalize": m.has_perm(Perm.POS_FINALIZE),
        "can_void": m.has_perm(Perm.POS_VOID), "can_discount": m.has_perm(Perm.POS_DISCOUNT),
        "can_validate": m.has_perm(Perm.POS_VALIDATE_QR),
        "customer_debt": customer_debt(ticket.customer) if ticket.customer_id and m.has_perm(Perm.CREDIT_MANAGE) else None})


@require_POST
@bar_required(Perm.POS_SELL, write=True)
def line_add(request, pk):
    ticket = _ticket(request, pk)
    form = LineForm(request.POST, bar=request.bar)
    if form.is_valid():
        d = form.cleaned_data
        try:
            add_line(ticket, d["product_bar"], d["quantity"], request.user, d["serving"])
        except SalesError as exc:
            messages.error(request, str(exc))
    else:
        _flash_errors(request, form)
    return redirect("sales:ticket_detail", pk=ticket.pk)


@require_POST
@bar_required(Perm.POS_VOID, write=True)
def line_void(request, pk, line_pk):
    ticket = _ticket(request, pk)
    line = get_object_or_404(TicketLine, pk=line_pk, ticket=ticket)
    form = VoidLineForm(request.POST)
    if form.is_valid():
        try:
            void_line(line, request.user, form.cleaned_data["reason"])
            messages.success(request, "Ligne annulée : le stock a été remis.")
        except SalesError as exc:
            messages.error(request, str(exc))
    else:
        _flash_errors(request, form)
    return redirect("sales:ticket_detail", pk=ticket.pk)


@require_POST
@bar_required(Perm.POS_DISCOUNT, write=True)
def ticket_discount(request, pk):
    form = DiscountForm(request.POST)
    if not form.is_valid():
        _flash_errors(request, form)
        return redirect("sales:ticket_detail", pk=pk)
    return _act(request, pk, lambda t: set_discount(t, form.cleaned_data["discount_fcfa"], request.user),
                "Remise enregistrée.", after=lambda t: _notify_paid(request, t))


@require_POST
@bar_required(Perm.POS_SELL, write=True)
def ticket_invoice(request, pk):
    return _act(request, pk, request_payment, "Facture en attente de paiement.")


@require_POST
@bar_required(Perm.POS_FINALIZE, write=True)
def payment_add(request, pk):
    form = PaymentForm(request.POST)
    if not form.is_valid():
        _flash_errors(request, form)
        return redirect("sales:ticket_detail", pk=pk)
    d = form.cleaned_data

    def after(ticket):
        _notify_paid(request, ticket)
        _notify_payment(request, ticket, d["amount_fcfa"])

    return _act(request, pk, lambda t: add_payment(t, d["amount_fcfa"], d["method"], request.user, d["reference"]),
                "Paiement enregistré.", after=after)


@require_POST
@bar_required(Perm.POS_VOID, write=True)
def payment_refund(request, pk):
    form = RefundForm(request.POST)
    if not form.is_valid():
        _flash_errors(request, form)
        return redirect("sales:ticket_detail", pk=pk)
    d = form.cleaned_data
    return _act(request, pk, lambda t: refund_payment(t, d["amount_fcfa"], d["method"], request.user, d["justification"]),
                "Remboursement enregistré.")


@require_POST
@bar_required(Perm.POS_FINALIZE, write=True)
def ticket_finalize(request, pk):
    return _act(request, pk, lambda t: finalize_ticket(t, request.user), "Ticket finalisé.")


@require_POST
@bar_required(Perm.POS_VOID, write=True)
def ticket_cancel(request, pk):
    form = CancelForm(request.POST)
    if not form.is_valid():
        _flash_errors(request, form)
        return redirect("sales:ticket_detail", pk=pk)
    return _act(request, pk, lambda t: cancel_ticket(t, request.user, form.cleaned_data["reason"]),
                "Ticket annulé : le stock a été remis.")


# ================================================================== commandes QR
@require_POST
@bar_required(Perm.POS_VALIDATE_QR, write=True)
def qr_validate(request, pk):
    return _act(request, pk, lambda t: validate_qr_ticket(t, request.user), "Commande validée : stock mis à jour.")


@require_POST
@bar_required(Perm.POS_VALIDATE_QR, write=True)
def qr_reject(request, pk):
    return _act(request, pk, lambda t: cancel_ticket(t, request.user, "Commande QR rejetée"), "Commande rejetée.")


# ================================================================== clients et crédits
@bar_required(CUSTOMER_ROLES)
def customer_list(request):
    qs = (Customer.objects.filter(bar=request.bar)
          .annotate(debt=Sum(F("tickets__total_fcfa") - F("tickets__amount_paid_fcfa"),
                             filter=Q(tickets__status=Status.FINALIZED))))
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q))
    only_debt = request.GET.get("debt") == "1"
    if only_debt:
        qs = qs.filter(debt__gt=0)
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "sales/customer_list.html", {"page": page, "q": q, "only_debt": only_debt})


@bar_required(Perm.CREDIT_MANAGE, write=True)
def customer_create(request):
    form = CustomerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        customer = form.save(commit=False)
        customer.bar = request.bar
        customer.save()
        messages.success(request, f"Client « {customer} » créé.")
        return redirect("sales:customer_detail", pk=customer.pk)
    return _form_page(request, form, "Nouveau client", "sales:customer_list")


@bar_required(Perm.CREDIT_MANAGE, write=True)
def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk, bar=request.bar)
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Client mis à jour.")
        return redirect("sales:customer_detail", pk=customer.pk)
    return _form_page(request, form, f"Modifier {customer}", "sales:customer_detail", back_args=[customer.pk])


@bar_required(CUSTOMER_ROLES)
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk, bar=request.bar)
    unpaid = [t for t in customer.tickets.filter(status=Status.FINALIZED).order_by("business_date")
              if t.balance_due_fcfa > 0]
    page = Paginator(customer.tickets.exclude(status=Status.CANCELLED), 20).get_page(request.GET.get("page"))
    return render(request, "sales/customer_detail.html", {
        "customer": customer, "debt": customer_debt(customer), "unpaid": unpaid, "page": page})


# ================================================================== rapport de ventes
@bar_required(Perm.REPORT_VIEW)
def sales_report_view(request):
    bar = request.bar
    form = ReportForm(request.GET)
    form.is_valid()
    period = form.cleaned_data.get("period") or PeriodType.DAY
    ref = form.cleaned_data.get("date") or bar.current_business_date()
    start, end = period_bounds(period, ref)
    rows, by_method, totals = sales_report(bar, start, end)
    return render(request, "sales/report.html", {
        "form": form, "period": period, "start": start, "end": end, "rows": rows,
        "by_method": by_method, "totals": totals, "periods": PeriodType.choices})