from django.db import models

# Create your models here.


import re
import unicodedata
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum

from core.models import BarScopedModel, TimeStampedModel


def normalize_name(value: str) -> str:
    """Sert à détecter les doublons : « Castel 65cl » ≈ « CASTEL 65 CL »."""
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", value.lower())


class Category(TimeStampedModel):
    class Kind(models.TextChoices):
        BEER = "BEER", "Bière"
        WINE = "WINE", "Vin"
        SPIRIT = "SPIRIT", "Whisky / spiritueux"
        JUICE = "JUICE", "Jus"
        SOFT = "SOFT", "Boisson gazeuse"
        WATER = "WATER", "Eau"
        OTHER = "OTHER", "Autre"

    name = models.CharField(max_length=80)
    slug = models.SlugField(unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.OTHER)

    class Meta:
        verbose_name_plural = "catégories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProductGlobal(TimeStampedModel):
    """Catalogue commun à tous les bars (identité du produit, SANS prix)."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "En attente de modération"
        APPROVED = "APPROVED", "Validé"
        REJECTED = "REJECTED", "Rejeté"

    name = models.CharField(max_length=150)
    brand = models.CharField(max_length=100, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    volume_cl = models.PositiveIntegerField("volume (cl)", null=True, blank=True)
    alcohol_percent = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    barcode = models.CharField(max_length=40, blank=True, db_index=True)
    image = models.ImageField(upload_to="products/", null=True, blank=True)
    normalized_name = models.CharField(max_length=160, db_index=True, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.APPROVED)
    # Si un bar a proposé ce produit : sert à la modération et à la détection de doublons.
    created_by_bar = models.ForeignKey(
        "tenants.Bar", null=True, blank=True, on_delete=models.SET_NULL, related_name="proposed_products"
    )
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="duplicates")
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["normalized_name", "volume_cl"])]
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.normalized_name = normalize_name(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} {self.volume_cl or ''}cl".strip()


class ProductBar(BarScopedModel):
    """Produit tel que vendu par UN bar : prix et seuils propres au bar."""

    product = models.ForeignKey(ProductGlobal, on_delete=models.PROTECT, related_name="bar_products")
    sale_price_fcfa = models.PositiveIntegerField("prix de vente / unité de base")
    purchase_price_fcfa = models.PositiveIntegerField("prix d'achat / unité de base", default=0)
    price_effective_from = models.DateField(default=date.today)
    low_stock_threshold = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bar", "product"], name="uniq_product_per_bar")]
        ordering = ["product__name"]

    def __str__(self):
        return f"{self.product} @ {self.bar}"

    def current_stock(self) -> Decimal:
        total = self.lots.filter(status="OPEN").aggregate(t=Sum("remaining_qty"))["t"]
        return total or Decimal("0")

    @property
    def is_low_stock(self) -> bool:
        return self.current_stock() <= self.low_stock_threshold


class ProductPriceHistory(BarScopedModel):
    product_bar = models.ForeignKey(ProductBar, on_delete=models.CASCADE, related_name="price_history")
    sale_price_fcfa = models.PositiveIntegerField()
    purchase_price_fcfa = models.PositiveIntegerField(default=0)
    effective_from = models.DateField()
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-effective_from", "-id"]


class PackagingUnit(BarScopedModel):
    """Conditionnement d'achat : casier, palette, carton, pack de canettes…"""

    class Kind(models.TextChoices):
        CRATE = "CRATE", "Casier"
        PALLET = "PALLET", "Palette"
        CARTON = "CARTON", "Carton"
        PACK = "PACK", "Pack / paquet"
        UNIT = "UNIT", "Unité"

    product_bar = models.ForeignKey(ProductBar, on_delete=models.CASCADE, related_name="packagings")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.CRATE)
    name = models.CharField(max_length=80, help_text="ex : Casier de 12")
    units_per_package = models.PositiveIntegerField("unités de base par conditionnement")
    is_default_purchase = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.units_per_package} u.)"


class ServingOption(BarScopedModel):
    """Vente fractionnée : verre de vin, mesure de whisky (fraction de l'unité de base)."""

    product_bar = models.ForeignKey(ProductBar, on_delete=models.CASCADE, related_name="servings")
    name = models.CharField(max_length=60, help_text="ex : Verre, Mesure 4 cl")
    base_units = models.DecimalField(max_digits=8, decimal_places=4, help_text="ex : 0.2 = 1/5 de bouteille")
    price_fcfa = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} – {self.product_bar}"
