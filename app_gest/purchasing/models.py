from django.db import models

# Create your models here.


from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from core.models import BarScopedModel, PaymentMethod


class Supplier(BarScopedModel):
    name = models.CharField(max_length=150)
    contact_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PurchaseOrder(BarScopedModel):
    """Commande au fournisseur (dépôt) : payée d'avance ou à crédit."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Brouillon"
        SENT = "SENT", "Envoyée"
        PARTIAL = "PARTIAL", "Reçue partiellement"
        RECEIVED = "RECEIVED", "Reçue"
        CLOSED = "CLOSED", "Clôturée"
        CANCELLED = "CANCELLED", "Annulée"

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Non payée"
        PARTIAL = "PARTIAL", "Partiellement payée"
        PAID = "PAID", "Payée"

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="orders")
    reference = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    ordered_at = models.DateField(default=timezone.localdate)
    expected_at = models.DateField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    on_credit = models.BooleanField("à crédit", default=False)
    due_date = models.DateField("échéance", null=True, blank=True)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    total_fcfa = models.BigIntegerField(default=0)
    amount_paid_fcfa = models.BigIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-ordered_at", "-id"]
        indexes = [models.Index(fields=["bar", "payment_status", "due_date"])]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.reference:  # le pk garantit l'unicité sans course critique
            self.reference = f"PO-{self.ordered_at:%y%m}-{self.pk:05d}"
            super().save(update_fields=["reference"])

    @property
    def balance_due_fcfa(self):
        return self.total_fcfa - self.amount_paid_fcfa

    def recalc(self):
        total = sum(l.line_total_fcfa for l in self.lines.all())
        paid = self.payments.aggregate(t=Sum("amount_fcfa"))["t"] or 0
        self.total_fcfa, self.amount_paid_fcfa = int(total), paid
        if paid <= 0:
            self.payment_status = self.PaymentStatus.UNPAID
        elif paid >= self.total_fcfa:
            self.payment_status = self.PaymentStatus.PAID
        else:
            self.payment_status = self.PaymentStatus.PARTIAL
        self.save(update_fields=["total_fcfa", "amount_paid_fcfa", "payment_status", "updated_at"])

    def __str__(self):
        return self.reference or f"Commande #{self.pk}"


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    product_bar = models.ForeignKey("catalog.ProductBar", on_delete=models.PROTECT, related_name="purchase_lines")
    packaging = models.ForeignKey("catalog.PackagingUnit", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    quantity_packages = models.PositiveIntegerField("nb de casiers / cartons / palettes")
    units_per_package = models.PositiveIntegerField(help_text="Copie figée du conditionnement")
    package_cost_fcfa = models.PositiveIntegerField("prix par conditionnement")
    received_packages = models.PositiveIntegerField(default=0)

    @property
    def base_quantity(self) -> int:
        return self.quantity_packages * self.units_per_package

    @property
    def unit_cost_fcfa(self) -> Decimal:
        return Decimal(self.package_cost_fcfa) / Decimal(self.units_per_package)

    @property
    def line_total_fcfa(self) -> int:
        return self.quantity_packages * self.package_cost_fcfa


class SupplierPayment(BarScopedModel):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="payments")
    amount_fcfa = models.PositiveIntegerField()
    method = models.CharField(max_length=15, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    paid_at = models.DateTimeField(default=timezone.now)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    reference = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-paid_at"]
