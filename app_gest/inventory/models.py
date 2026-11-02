from django.db import models

# Create your models here.


from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import BarScopedModel, BarScopedQuerySet, PeriodType


class StockLotQuerySet(BarScopedQuerySet):
    def fifo(self, bar, product_bar):
        """Lots à consommer dans l'ordre : le plus ancien d'abord (règle FIFO)."""
        return (
            self.filter(bar=bar, product_bar=product_bar, status=StockLot.Status.OPEN, remaining_qty__gt=0)
            .order_by("received_at", "id")
            .select_for_update()
        )


class StockLot(BarScopedModel):
    """Un lot = une réception de commande. Les ventes vident le plus ancien en premier."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "En cours"
        DEPLETED = "DEPLETED", "Épuisé"

    class Source(models.TextChoices):
        PURCHASE = "PURCHASE", "Commande fournisseur"
        OPENING = "OPENING", "Stock initial"
        ADJUSTMENT = "ADJUSTMENT", "Ajustement"

    product_bar = models.ForeignKey("catalog.ProductBar", on_delete=models.PROTECT, related_name="lots")
    purchase_line = models.ForeignKey(
        "purchasing.PurchaseOrderLine", null=True, blank=True, on_delete=models.SET_NULL, related_name="lots"
    )
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.PURCHASE)
    received_at = models.DateTimeField(default=timezone.now)
    initial_qty = models.DecimalField(max_digits=12, decimal_places=3)
    remaining_qty = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost_fcfa = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)

    objects = StockLotQuerySet.as_manager()

    class Meta:
        ordering = ["received_at", "id"]
        indexes = [models.Index(fields=["bar", "product_bar", "status", "received_at"])]
        constraints = [
            models.CheckConstraint(condition=Q(remaining_qty__gte=0), name="lot_remaining_non_negative")
        ]

    def __str__(self):
        return f"Lot {self.pk} – {self.product_bar} ({self.remaining_qty}/{self.initial_qty})"


class LossReport(BarScopedModel):
    """Perte signalée par le vendeur (bouteille cassée…), validée par le gérant."""

    class Reason(models.TextChoices):
        BREAKAGE = "BREAKAGE", "Casse"
        EXPIRED = "EXPIRED", "Périmé"
        THEFT = "THEFT", "Vol / disparition"
        GIVEN = "GIVEN", "Offert"
        OTHER = "OTHER", "Autre"

    class Status(models.TextChoices):
        PENDING = "PENDING", "En attente"
        APPROVED = "APPROVED", "Validée"
        REJECTED = "REJECTED", "Rejetée"

    product_bar = models.ForeignKey("catalog.ProductBar", on_delete=models.PROTECT, related_name="losses")
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    reason = models.CharField(max_length=10, choices=Reason.choices, default=Reason.BREAKAGE)
    note = models.CharField(max_length=255, blank=True)
    photo = models.ImageField(upload_to="losses/", null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    declared_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    business_date = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["-created_at"]


class StockMovement(BarScopedModel):
    """Journal APPEND-ONLY : le stock est toujours la somme des mouvements."""

    class Kind(models.TextChoices):
        OPENING = "OPENING", "Stock initial"
        PURCHASE_IN = "PURCHASE_IN", "Entrée (commande reçue)"
        SALE_OUT = "SALE_OUT", "Sortie (vente)"
        LOSS_OUT = "LOSS_OUT", "Sortie (perte)"
        FREE_OUT = "FREE_OUT", "Sortie (offert)"
        ADJUST_IN = "ADJUST_IN", "Ajustement +"
        ADJUST_OUT = "ADJUST_OUT", "Ajustement −"
        RETURN_IN = "RETURN_IN", "Retour (annulation vente)"

    product_bar = models.ForeignKey("catalog.ProductBar", on_delete=models.PROTECT, related_name="movements")
    lot = models.ForeignKey(StockLot, null=True, blank=True, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, help_text="Signée : + entrée, − sortie")
    unit_cost_fcfa = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    business_date = models.DateField(null=True, blank=True, db_index=True)
    ticket_line = models.ForeignKey("sales.TicketLine", null=True, blank=True, on_delete=models.PROTECT, related_name="movements")
    loss_report = models.ForeignKey(LossReport, null=True, blank=True, on_delete=models.PROTECT, related_name="movements")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [models.Index(fields=["bar", "product_bar", "occurred_at"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Les mouvements de stock sont immuables : créez un mouvement correctif.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Les mouvements de stock ne peuvent pas être supprimés.")


class InventoryCount(BarScopedModel):
    """Inventaire physique (comptage) sur une période : jour, semaine, mois, trimestre, année."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Brouillon"
        IN_PROGRESS = "IN_PROGRESS", "Comptage en cours"
        VALIDATED = "VALIDATED", "Validé"

    period_type = models.CharField(max_length=8, choices=PeriodType.choices, default=PeriodType.DAY)
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    counted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    validated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    validated_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-period_end", "-id"]


class InventoryCountLine(models.Model):
    count = models.ForeignKey(InventoryCount, on_delete=models.CASCADE, related_name="lines")
    product_bar = models.ForeignKey("catalog.ProductBar", on_delete=models.PROTECT, related_name="+")
    theoretical_qty = models.DecimalField(max_digits=12, decimal_places=3)
    counted_qty = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    unit_cost_fcfa = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    adjustment_movement = models.ForeignKey(StockMovement, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["count", "product_bar"], name="uniq_count_product")]

    @property
    def difference(self) -> Decimal:
        return (self.counted_qty or Decimal("0")) - self.theoretical_qty

    @property
    def difference_value_fcfa(self) -> Decimal:
        return self.difference * self.unit_cost_fcfa


class DailyClosing(BarScopedModel):
    """Clôture journalière : photo du stock et des ventes. Semaine/mois/trimestre/année
    s'obtiennent en AGRÉGEANT ces clôtures (pas cinq mécanismes différents)."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Ouverte"
        CLOSED = "CLOSED", "Clôturée"

    business_date = models.DateField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    cash_expected_fcfa = models.BigIntegerField(default=0)
    cash_counted_fcfa = models.BigIntegerField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bar", "business_date"], name="uniq_closing_per_day")]
        ordering = ["-business_date"]


class DailyClosingLine(models.Model):
    closing = models.ForeignKey(DailyClosing, on_delete=models.CASCADE, related_name="lines")
    product_bar = models.ForeignKey("catalog.ProductBar", on_delete=models.PROTECT, related_name="+")
    opening_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    in_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    sold_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    lost_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    adjust_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    closing_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    revenue_fcfa = models.BigIntegerField(default=0)
    cogs_fcfa = models.BigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["closing", "product_bar"], name="uniq_closing_product")]
