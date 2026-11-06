from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import bar_required
from accounts.permissions import Perm

from .forms import CreditCreateForm, CreditPaymentForm, DueDateForm, ReminderForm, WriteOffForm
from .models import CustomerCredit
from .services import (ACTIVE, CreditError, add_credit_payment, contact_link, create_manual_credit,
                       credit_summary, record_reminder, reminder_message, set_due_date, write_off_credit)

Status = CustomerCredit.Status


class SchemeRedirect(HttpResponseRedirect):
    """Redirection vers WhatsApp (https) ou vers les applications SMS / téléphone du mobile."""
    allowed_schemes = ["http", "https", "sms", "tel"]


def _form_page(request, form, title, back_url, back_args=None, submit="Enregistrer", subtitle=""):
    return render(request, "credits/form.html", {
        "form": form, "title": title, "back_url": back_url, "back_args": back_args or [],
        "submit": submit, "subtitle": subtitle})


def _credit(request, pk):
    return get_object_or_404(CustomerCredit.objects.select_related("customer", "ticket", "approved_by"),
                             pk=pk, bar=request.bar)


def _flash_errors(request, form):
    for errors in form.errors.values():
        for err in errors:
            messages.error(request, err)


# ================================================================== créances
@bar_required(Perm.CREDIT_MANAGE)
def credit_list(request):
    bar = request.bar
    today = bar.current_business_date()
    qs = CustomerCredit.objects.filter(bar=bar).select_related("customer", "ticket")
    state = request.GET.get("state", "actifs")
    if state == "actifs":
        qs = qs.filter(status__in=ACTIVE)
    elif state == "retard":
        qs = qs.filter(status__in=ACTIVE, due_date__lt=today)
    elif state == "soldees":
        qs = qs.filter(status=Status.SETTLED)
    elif state == "pertes":
        qs = qs.filter(status=Status.WRITTEN_OFF)
    else:
        state = "toutes"
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(customer__name__icontains=q) | Q(customer__phone__icontains=q))
    customer = request.GET.get("customer", "")
    if customer.isdigit():
        qs = qs.filter(customer_id=int(customer))
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "credits/credit_list.html", {
        "page": page, "state": state, "q": q, "customer": customer, "today": today,
        "querystring": params.urlencode(), "summary": credit_summary(bar)})


@bar_required(Perm.CREDIT_MANAGE, write=True)
def credit_create(request):
    form = CreditCreateForm(request.POST or None, bar=request.bar)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            credit = create_manual_credit(request.bar, d["customer"], d["amount_fcfa"], request.user,
                                          d["due_date"], d["note"])
        except CreditError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Créance enregistrée.")
            return redirect("credits:credit_detail", pk=credit.pk)
    return _form_page(request, form, "Nouvelle créance", "credits:credit_list", submit="Enregistrer la créance",
                      subtitle="Pour une dette antérieure à l'application. Les ventes à crédit créent leur créance automatiquement.")


@bar_required(Perm.CREDIT_MANAGE)
def credit_detail(request, pk):
    credit = _credit(request, pk)
    active = credit.status in ACTIVE
    return render(request, "credits/credit_detail.html", {
        "credit": credit, "active": active,
        "payments": list(credit.payments.select_related("received_by")),
        "reminders": list(credit.reminders.select_related("sent_by")),
        "payment_form": CreditPaymentForm(initial={"amount_fcfa": credit.balance_fcfa}),
        "due_form": DueDateForm(initial={"due_date": credit.due_date}),
        "write_off_form": WriteOffForm(),
        "reminder_form": ReminderForm(initial={"message": reminder_message(credit)}) if active else None,
        "can_write_off": active and request.membership.is_owner})


@require_POST
@bar_required(Perm.CREDIT_MANAGE, write=True)
def payment_add(request, pk):
    credit = _credit(request, pk)
    form = CreditPaymentForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            add_credit_payment(credit, d["amount_fcfa"], d["method"], request.user, d["reference"])
        except CreditError as exc:
            messages.error(request, str(exc))
        else:
            credit.refresh_from_db()
            messages.success(request, "Règlement enregistré." if credit.balance_fcfa
                             else "Règlement enregistré : la créance est soldée.")
    else:
        _flash_errors(request, form)
    return redirect("credits:credit_detail", pk=credit.pk)


@require_POST
@bar_required(Perm.CREDIT_MANAGE, write=True)
def due_date_update(request, pk):
    credit = _credit(request, pk)
    form = DueDateForm(request.POST)
    if form.is_valid():
        try:
            set_due_date(credit, form.cleaned_data["due_date"])
            messages.success(request, "Échéance mise à jour.")
        except CreditError as exc:
            messages.error(request, str(exc))
    else:
        _flash_errors(request, form)
    return redirect("credits:credit_detail", pk=credit.pk)


@require_POST
@bar_required(Perm.CREDIT_MANAGE, write=True)
def credit_write_off(request, pk):
    credit = _credit(request, pk)
    if not request.membership.is_owner:
        messages.error(request, "Seul le gérant peut passer une créance en perte.")
        return redirect("credits:credit_detail", pk=credit.pk)
    form = WriteOffForm(request.POST)
    if form.is_valid():
        try:
            write_off_credit(credit, request.user, form.cleaned_data["reason"])
            messages.info(request, "Créance passée en perte.")
        except CreditError as exc:
            messages.error(request, str(exc))
    else:
        _flash_errors(request, form)
    return redirect("credits:credit_detail", pk=credit.pk)


@require_POST
@bar_required(Perm.CREDIT_MANAGE, write=True)
def reminder_add(request, pk):
    """Enregistre la relance dans l'historique, puis ouvre WhatsApp / SMS / téléphone avec le message prêt."""
    credit = _credit(request, pk)
    form = ReminderForm(request.POST)
    if not form.is_valid():
        _flash_errors(request, form)
        return redirect("credits:credit_detail", pk=credit.pk)
    channel = form.cleaned_data["channel"]
    try:
        _, message = record_reminder(credit, request.user, channel, form.cleaned_data["message"])
    except CreditError as exc:
        messages.error(request, str(exc))
        return redirect("credits:credit_detail", pk=credit.pk)
    link = contact_link(credit, channel, message)
    if link:
        return SchemeRedirect(link)
    if channel != "IN_APP":
        messages.warning(request, "Relance enregistrée, mais ce client n'a pas de numéro de téléphone.")
    else:
        messages.success(request, "Relance enregistrée.")
    return redirect("credits:credit_detail", pk=credit.pk)