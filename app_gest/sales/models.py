from django.db import models

# Create your models here.



import uuid

from django.conf import settings
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone

from core.models import BarScopedModel, PaymentMethod


def label_from_index(i: int) -> str:
    """0→ClientA1 … 9→ClientA10, 10→ClientB1 … 259→ClientZ10, 260→ClientAA1."""
    block, n = divmod(i, 10)
    block += 1
    letters = ""
    while block > 0:
        block, r = divmod(block - 1, 26)
        letters = chr(65 + r) + letters
    return f"Client{letters}{n + 1}"


class Customer(BarScopedModel):
    """Client IDENTIFIÉ (indispensable pour vendre à crédit). Le nom reste optionnel au comptoir."""

    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    credit_limit_fcfa = models.PositiveIntegerField("plafond de crédit", default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class TicketSequence(BarScopedModel):
    """Compteur journalier A1…A10, B1… : repart de zéro à chaque journée d'activité."""

    business_date = models.DateField()
    counter = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bar", "business_date"], name="uniq_sequence_per_day")]

    @classmethod
    @transaction.atomic
    def next_label(cls, bar):
        day = bar.current_business_date()
        seq, _ = cls.objects.select_for_update().get_or_create(bar=bar, business_date=day)
        idx = seq.counter
        seq.counter = idx + 1
        seq.save(update_fields=["counter", "updated_at"])
        return day, label_from_index(idx)


class Ticket(BarScopedModel):
    """Commande / facture d'un client. Se finalise quand le client a fini ET payé."""

    class Status(models.TextChoices):
        PENDING_VALIDATION = "PENDING_VALIDATION", "Commande QR à valider"
        OPEN = "OPEN", "Ouverte"
        AWAITING_PAYMENT = "AWAITING_PAYMENT", "Facture en attente"
        PAID = "PAID", "Payée"
        FINALIZED = "FINALIZED", "Finalisée"
        CANCELLED = "CANCELLED", "Annulée"

    class Source(models.TextChoices):
        POS = "POS", "Comptoir (vendeuse)"
        QR = "QR", "QR code (client)"

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Non payé"
        PARTIAL = "PARTIAL", "Partiellement payé"
        PAID = "PAID", "Payé"

    class PaymentTiming(models.TextChoices):
        IMMEDIATE = "IMMEDIATE", "Paye tout de suite"
        DEFERRED = "DEFERRED", "Paye après consommation"

    business_date = models.DateField(db_index=True)
    label = models.CharField("nom auto", max_length=20)          # ClientA1
    custom_name = models.CharField("nom du client (facultatif)", max_length=80, blank=True)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")
    source = models.CharField(max_length=4, choices=Source.choices, default=Source.POS)
    table_label = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    payment_timing = models.CharField(max_length=10, choices=PaymentTiming.choices, default=PaymentTiming.DEFERRED)
    payment_status = models.CharField(max_length=8, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)

    subtotal_fcfa = models.BigIntegerField(default=0)
    discount_fcfa = models.BigIntegerField(default=0)
    total_fcfa = models.BigIntegerField(default=0)
    amount_paid_fcfa = models.BigIntegerField(default=0)

    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    validated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    validated_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    finalized_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cancel_reason = models.CharField(max_length=255, blank=True)
    client_session = models.UUIDField(default=uuid.uuid4, editable=False, help_text="Suivi anonyme côté QR")
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bar", "business_date", "label"], name="uniq_ticket_label_per_day")]
        indexes = [models.Index(fields=["bar", "business_date", "status"])]
        ordering = ["-created_at"]

    @property
    def display_name(self):
        return self.custom_name or self.label

    @property
    def balance_due_fcfa(self):
        return self.total_fcfa - self.amount_paid_fcfa

    def recalc(self, save=True):
        subtotal = self.lines.filter(is_void=False).aggregate(t=Sum("line_total_fcfa"))["t"] or 0
        paid = self.payments.filter(kind=Payment.Kind.PAYMENT).aggregate(t=Sum("amount_fcfa"))["t"] or 0
        refunded = self.payments.filter(kind=Payment.Kind.REFUND).aggregate(t=Sum("amount_fcfa"))["t"] or 0
        self.subtotal_fcfa = subtotal
        self.total_fcfa = max(subtotal - self.discount_fcfa, 0)
        self.amount_paid_fcfa = paid - refunded
        if self.amount_paid_fcfa <= 0:
            self.payment_status = self.PaymentStatus.UNPAID
        elif self.amount_paid_fcfa < self.total_fcfa:
            self.payment_status = self.PaymentStatus.PARTIAL
        else:
            self.payment_status = self.PaymentStatus.PAID
        if save:
            self.save(update_fields=["subtotal_fcfa", "total_fcfa", "amount_paid_fcfa", "payment_status", "updated_at"])

    def __str__(self):
        return f"{self.display_name} ({self.business_date})"


class TicketLine(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="lines")
    product_bar = models.ForeignKey("catalog.ProductBar", on_delete=models.PROTECT, related_name="sale_lines")
    serving = models.ForeignKey("catalog.ServingOption", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    unit_price_fcfa = models.PositiveIntegerField(help_text="Prix figé au moment de la vente")
    line_total_fcfa = models.BigIntegerField(default=0)
    base_quantity = models.DecimalField(max_digits=10, decimal_places=3, default=0, help_text="Unités de base à sortir du stock")
    cogs_fcfa = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="Coût réel via lots FIFO")
    stock_consumed = models.BooleanField(default=False)
    is_void = models.BooleanField(default=False)
    void_reason = models.CharField(max_length=255, blank=True)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    added_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["added_at", "id"]

    def save(self, *args, **kwargs):
        self.line_total_fcfa = int(self.quantity * self.unit_price_fcfa)
        super().save(*args, **kwargs)


class Payment(BarScopedModel):
    """Encaissement. La justification « déjà payé / pas encore » = Ticket.payment_status + ces lignes."""

    class Kind(models.TextChoices):
        PAYMENT = "PAYMENT", "Paiement"
        REFUND = "REFUND", "Remboursement"

    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="payments")
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.PAYMENT)
    amount_fcfa = models.PositiveIntegerField()
    method = models.CharField(max_length=15, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    paid_at = models.DateTimeField(default=timezone.now, db_index=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    reference = models.CharField(max_length=80, blank=True)
    justification = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-paid_at"]
