from django.db import models

from core.models import BarScopedModel, PeriodType


class DailySalesSummary(BarScopedModel):
    """Alimenté chaque nuit (ou à la clôture) : base des tableaux de bord et prévisions."""

    business_date = models.DateField()
    tickets_count = models.PositiveIntegerField(default=0)
    revenue_fcfa = models.BigIntegerField(default=0)
    cogs_fcfa = models.BigIntegerField(default=0)
    gross_margin_fcfa = models.BigIntegerField(default=0)
    losses_fcfa = models.BigIntegerField(default=0)
    collected_fcfa = models.BigIntegerField(default=0)
    credit_granted_fcfa = models.BigIntegerField(default=0)
    peak_hour = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bar", "business_date"], name="uniq_daily_summary")]
        ordering = ["-business_date"]


class ProductDailyStat(BarScopedModel):
    product_bar = models.ForeignKey("catalog.ProductBar", on_delete=models.CASCADE, related_name="daily_stats")
    business_date = models.DateField()
    qty_sold = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    revenue_fcfa = models.BigIntegerField(default=0)
    cogs_fcfa = models.BigIntegerField(default=0)
    qty_lost = models.DecimalField(max_digits=12, decimal_places=3, default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bar", "product_bar", "business_date"], name="uniq_product_daily")]
        indexes = [models.Index(fields=["bar", "business_date"])]


class SalesForecast(BarScopedModel):
    product_bar = models.ForeignKey("catalog.ProductBar", null=True, blank=True, on_delete=models.CASCADE, related_name="forecasts")
    granularity = models.CharField(max_length=8, choices=PeriodType.choices, default=PeriodType.DAY)
    target_start = models.DateField()
    predicted_qty = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    predicted_revenue_fcfa = models.BigIntegerField(null=True, blank=True)
    predicted_stockout_date = models.DateField(null=True, blank=True)
    suggested_order_qty = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    method = models.CharField(max_length=40, default="moving_average_weekday")
    confidence = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["-target_start"]


class Recommendation(BarScopedModel):
    class Kind(models.TextChoices):
        PROMOTE = "PROMOTE", "Mettre en avant"
        RESTOCK = "RESTOCK", "Réapprovisionner"
        HAPPY_HOUR = "HAPPY_HOUR", "Promotion horaire"
        PRICE_REVIEW = "PRICE_REVIEW", "Revoir le prix"
        SLOW_MOVER = "SLOW_MOVER", "Faible rotation"
        CREDIT_RISK = "CREDIT_RISK", "Risque de crédit"

    class Status(models.TextChoices):
        NEW = "NEW", "Nouvelle"
        SEEN = "SEEN", "Vue"
        APPLIED = "APPLIED", "Appliquée"
        DISMISSED = "DISMISSED", "Ignorée"

    kind = models.CharField(max_length=14, choices=Kind.choices)
    product_bar = models.ForeignKey("catalog.ProductBar", null=True, blank=True, on_delete=models.CASCADE, related_name="recommendations")
    title = models.CharField(max_length=150)
    message = models.TextField()
    priority = models.PositiveSmallIntegerField(default=3)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW)
    generated_by = models.CharField(max_length=10, default="RULES")  # RULES | LLM
    payload = models.JSONField(default=dict, blank=True)
    valid_until = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["priority", "-created_at"]
