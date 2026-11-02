from django.db import models

# Create your models here.


from django.conf import settings
from django.db import models


class PeriodType(models.TextChoices):
    DAY = "DAY", "Jour"
    WEEK = "WEEK", "Semaine"
    MONTH = "MONTH", "Mois"
    QUARTER = "QUARTER", "Trimestre"
    YEAR = "YEAR", "Année"


class PaymentMethod(models.TextChoices):
    CASH = "CASH", "Espèces"
    MTN_MOMO = "MTN_MOMO", "MTN Mobile Money"
    ORANGE_MONEY = "ORANGE_MONEY", "Orange Money"
    BANK = "BANK", "Virement / banque"
    CARD = "CARD", "Carte"
    OTHER = "OTHER", "Autre"


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BarScopedQuerySet(models.QuerySet):
    def for_bar(self, bar):
        return self.filter(bar=bar)


class BarScopedModel(TimeStampedModel):
    """Base de tout modèle appartenant à un bar (multi-tenant par clé `bar`)."""

    bar = models.ForeignKey(
        "tenants.Bar",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
    )
    objects = BarScopedQuerySet.as_manager()

    class Meta:
        abstract = True


class AuditLog(BarScopedModel):
    """Journal d'audit : qui a fait quoi (annulations, remises, ajustements, etc.)."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    action = models.CharField(max_length=80)
    target_model = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=40, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["bar", "-created_at"])]

    def __str__(self):
        return f"{self.action} ({self.target_model}#{self.target_id})"
