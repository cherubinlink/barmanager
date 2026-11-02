
# Create your models here.



from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import BarScopedModel, PaymentMethod


class CustomerCredit(BarScopedModel):
    """Créance : un client consomme maintenant et paie plus tard.
    (Les dettes fournisseurs sont portées par purchasing.PurchaseOrder + SupplierPayment.)"""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Ouvert"
        PARTIAL = "PARTIAL", "Partiellement réglé"
        SETTLED = "SETTLED", "Soldé"
        WRITTEN_OFF = "WRITTEN_OFF", "Passé en perte"

    customer = models.ForeignKey("sales.Customer", on_delete=models.PROTECT, related_name="credits")
    ticket = models.OneToOneField("sales.Ticket", null=True, blank=True, on_delete=models.SET_NULL, related_name="credit")
    amount_fcfa = models.BigIntegerField()
    amount_paid_fcfa = models.BigIntegerField(default=0)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["due_date", "-created_at"]
        indexes = [models.Index(fields=["bar", "status", "due_date"])]

    @property
    def balance_fcfa(self):
        return self.amount_fcfa - self.amount_paid_fcfa

    @property
    def is_overdue(self):
        return bool(self.due_date and self.status in ("OPEN", "PARTIAL") and self.due_date < timezone.localdate())


class CustomerCreditPayment(BarScopedModel):
    credit = models.ForeignKey(CustomerCredit, on_delete=models.CASCADE, related_name="payments")
    amount_fcfa = models.PositiveIntegerField()
    method = models.CharField(max_length=15, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    paid_at = models.DateTimeField(default=timezone.now)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    reference = models.CharField(max_length=80, blank=True)


class PaymentReminder(BarScopedModel):
    """Relance de paiement (créance client ou dette fournisseur)."""

    class Channel(models.TextChoices):
        IN_APP = "IN_APP", "Notification"
        SMS = "SMS", "SMS"
        WHATSAPP = "WHATSAPP", "WhatsApp"
        CALL = "CALL", "Appel"

    customer_credit = models.ForeignKey(CustomerCredit, null=True, blank=True, on_delete=models.CASCADE, related_name="reminders")
    purchase_order = models.ForeignKey("purchasing.PurchaseOrder", null=True, blank=True, on_delete=models.CASCADE, related_name="reminders")
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.IN_APP)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    message = models.CharField(max_length=255, blank=True)

