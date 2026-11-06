import re
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import CustomerCredit, CustomerCreditPayment, PaymentReminder

Status = CustomerCredit.Status
Channel = PaymentReminder.Channel
ACTIVE = (Status.OPEN, Status.PARTIAL)


class CreditError(Exception):
    pass


# ------------------------------------------------------------------ lecture
def customer_debt(customer):
    """Dette d'un client = solde restant de ses créances en cours."""
    r = CustomerCredit.objects.filter(customer=customer, status__in=ACTIVE).aggregate(
        t=Sum("amount_fcfa"), p=Sum("amount_paid_fcfa"))
    return (r["t"] or 0) - (r["p"] or 0)


def credit_summary(bar):
    """Chiffres clés : total dû, nombre de créances, et part en retard."""
    today = bar.current_business_date()
    active = CustomerCredit.objects.filter(bar=bar, status__in=ACTIVE)
    agg = active.aggregate(t=Sum("amount_fcfa"), p=Sum("amount_paid_fcfa"))
    late = active.filter(due_date__lt=today)
    late_agg = late.aggregate(t=Sum("amount_fcfa"), p=Sum("amount_paid_fcfa"))
    return {"debt": (agg["t"] or 0) - (agg["p"] or 0), "count": active.count(),
            "overdue_count": late.count(), "overdue_debt": (late_agg["t"] or 0) - (late_agg["p"] or 0)}


# ------------------------------------------------------------------ création
@transaction.atomic
def open_credit(ticket, user, due_date=None, note=""):
    """Appelée à la finalisation d'un ticket qui garde un solde : le reste à payer devient une créance."""
    if not ticket.customer_id:
        raise CreditError("Un client identifié est nécessaire pour vendre à crédit.")
    due = ticket.balance_due_fcfa
    if due <= 0:
        raise CreditError("Ce ticket est entièrement payé : aucune créance à créer.")
    days = getattr(settings, "CREDIT_DEFAULT_DAYS", 30)
    return CustomerCredit.objects.create(
        bar=ticket.bar, customer=ticket.customer, ticket=ticket, amount_fcfa=due,
        due_date=due_date or ticket.business_date + timedelta(days=days), approved_by=user, note=note)


@transaction.atomic
def create_manual_credit(bar, customer, amount, user, due_date=None, note=""):
    """Créance saisie à la main (dette antérieure à l'application, avance exceptionnelle…)."""
    if customer.bar_id != bar.id:
        raise CreditError("Client inconnu dans ce bar.")
    if amount <= 0:
        raise CreditError("Le montant doit être supérieur à 0.")
    return CustomerCredit.objects.create(bar=bar, customer=customer, amount_fcfa=amount, due_date=due_date,
                                         approved_by=user, note=note)


# ------------------------------------------------------------------ règlements
@transaction.atomic
def add_credit_payment(credit, amount, method, user, reference=""):
    credit = CustomerCredit.objects.select_for_update().get(pk=credit.pk)
    if credit.status not in ACTIVE:
        raise CreditError("Cette créance n'accepte plus de règlement.")
    if amount <= 0:
        raise CreditError("Le montant doit être supérieur à 0.")
    if amount > credit.balance_fcfa:
        raise CreditError(f"Le montant dépasse le reste dû ({credit.balance_fcfa} FCFA).")
    payment = CustomerCreditPayment.objects.create(
        bar=credit.bar, credit=credit, amount_fcfa=amount, method=method, received_by=user, reference=reference)
    credit.amount_paid_fcfa += amount
    credit.status = Status.SETTLED if credit.balance_fcfa <= 0 else Status.PARTIAL
    credit.save(update_fields=["amount_paid_fcfa", "status", "updated_at"])
    return payment


@transaction.atomic
def write_off_credit(credit, user, reason):
    """Passe le reste dû en perte (client introuvable, insolvable…). Le motif est conservé dans la note."""
    credit = CustomerCredit.objects.select_for_update().get(pk=credit.pk)
    if credit.status not in ACTIVE:
        raise CreditError("Cette créance est déjà clôturée.")
    stamp = f"[Perte {timezone.localdate():%d/%m/%Y} par {user}] {reason}"
    credit.note = f"{credit.note}\n{stamp}".strip()[:255]
    credit.status = Status.WRITTEN_OFF
    credit.save(update_fields=["status", "note", "updated_at"])
    return credit


@transaction.atomic
def set_due_date(credit, due_date):
    credit = CustomerCredit.objects.select_for_update().get(pk=credit.pk)
    if credit.status not in ACTIVE:
        raise CreditError("Cette créance est déjà clôturée.")
    credit.due_date = due_date
    credit.save(update_fields=["due_date", "updated_at"])
    return credit


# ------------------------------------------------------------------ relances
def reminder_message(credit):
    text = (f"Bonjour {credit.customer.name}, nous vous rappelons que vous devez {credit.balance_fcfa} FCFA "
            f"à {credit.bar.name}")
    if credit.due_date:
        text += f" (échéance : {credit.due_date:%d/%m/%Y})"
    return text + ". Merci de passer régler au plus tôt."


def _phone_digits(phone):
    raw = (phone or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return digits
    if digits.startswith("00"):
        return digits[2:]
    return getattr(settings, "CREDIT_PHONE_PREFIX", "237") + digits.lstrip("0")


def contact_link(credit, channel, message):
    """Lien qui ouvre WhatsApp, l'application SMS ou le téléphone ; '' si pas de numéro ou canal interne."""
    digits = _phone_digits(credit.customer.phone)
    if not digits:
        return ""
    if channel == Channel.WHATSAPP:
        return f"https://wa.me/{digits}?text={quote(message)}"
    if channel == Channel.SMS:
        return f"sms:+{digits}?body={quote(message)}"
    if channel == Channel.CALL:
        return f"tel:+{digits}"
    return ""


def record_reminder(credit, user, channel, message=""):
    if credit.status not in ACTIVE:
        raise CreditError("Cette créance est déjà clôturée.")
    message = (message or reminder_message(credit)).strip()
    reminder = PaymentReminder.objects.create(bar=credit.bar, customer_credit=credit, channel=channel,
                                              sent_by=user, message=message[:255])
    return reminder, message