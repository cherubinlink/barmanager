from django import forms
from django.db import transaction
from django.utils import timezone

from .models import (Category, PackagingUnit, ProductBar, ProductGlobal,
                     ServingOption, normalize_name)
from .services import visible_global_products


def _date_field(label):
    return forms.DateField(
        label=label, initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))


class ProductBarForm(forms.ModelForm):
    """Prix et seuil d'un produit POUR CE BAR (chaque bar fixe les siens)."""

    price_effective_from = _date_field("Prix applicable depuis le")

    class Meta:
        model = ProductBar
        fields = ["sale_price_fcfa", "purchase_price_fcfa", "price_effective_from",
                  "low_stock_threshold", "is_active"]
        labels = {
            "sale_price_fcfa": "Prix de vente d'une unité (FCFA)",
            "purchase_price_fcfa": "Prix d'achat d'une unité (FCFA)",
            "low_stock_threshold": "Seuil d'alerte de stock bas (unités)",
            "is_active": "Vendu dans ce bar",
        }
        help_texts = {
            "sale_price_fcfa": "Prix d'une bouteille (ou canette) vendue au client.",
            "purchase_price_fcfa": "Prix d'UNE bouteille chez votre fournisseur actuel.",
            "low_stock_threshold": "Vous serez alerté quand le stock passe sous ce niveau.",
        }

    def __init__(self, *args, show_active=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not show_active:
            del self.fields["is_active"]

    def clean_sale_price_fcfa(self):
        value = self.cleaned_data["sale_price_fcfa"]
        if value <= 0:
            raise forms.ValidationError("Le prix de vente doit être supérieur à 0.")
        return value

    def clean_price_effective_from(self):
        value = self.cleaned_data["price_effective_from"]
        if value > timezone.localdate():
            raise forms.ValidationError("La date ne peut pas être dans le futur : le prix s'applique immédiatement.")
        return value


class ProposeProductForm(forms.Form):
    """Un bar ajoute un produit que le catalogue ne connaît pas encore.
    Il l'utilise tout de suite ; la plateforme le valide ensuite pour les autres bars."""

    name = forms.CharField(label="Nom du produit", max_length=150, help_text="ex : Castel Beer")
    brand = forms.CharField(label="Marque", max_length=100, required=False)
    category = forms.ModelChoiceField(label="Catégorie", queryset=Category.objects.all())
    volume_cl = forms.IntegerField(label="Volume (cl)", min_value=1, required=False)
    alcohol_percent = forms.DecimalField(label="Degré d'alcool (%)", required=False, min_value=0,
                                         max_value=100, max_digits=4, decimal_places=1)
    sale_price_fcfa = forms.IntegerField(label="Prix de vente d'une unité (FCFA)", min_value=1)
    purchase_price_fcfa = forms.IntegerField(label="Prix d'achat d'une unité (FCFA)", min_value=0, initial=0)
    low_stock_threshold = forms.DecimalField(label="Seuil d'alerte de stock bas (unités)", min_value=0,
                                             max_digits=10, decimal_places=3, initial=0)

    def __init__(self, *args, bar, **kwargs):
        super().__init__(*args, **kwargs)
        self.bar = bar

    def clean(self):
        data = super().clean()
        name = data.get("name")
        if name:
            duplicate = visible_global_products(self.bar).filter(
                normalized_name=normalize_name(name), volume_cl=data.get("volume_cl")).first()
            if duplicate:
                raise forms.ValidationError(
                    f"« {duplicate} » existe déjà dans le catalogue. Utilisez « Ajouter un produit » "
                    "pour le retrouver au lieu de le recréer.")
        return data

    @transaction.atomic
    def save(self):
        d = self.cleaned_data
        product = ProductGlobal.objects.create(
            name=d["name"].strip(), brand=d["brand"].strip(), category=d["category"],
            volume_cl=d["volume_cl"], alcohol_percent=d["alcohol_percent"],
            status=ProductGlobal.Status.PENDING, created_by_bar=self.bar)
        return ProductBar.objects.create(
            bar=self.bar, product=product, sale_price_fcfa=d["sale_price_fcfa"],
            purchase_price_fcfa=d["purchase_price_fcfa"], low_stock_threshold=d["low_stock_threshold"],
            price_effective_from=timezone.localdate())


class PackagingForm(forms.ModelForm):
    class Meta:
        model = PackagingUnit
        fields = ["kind", "name", "units_per_package", "is_default_purchase"]
        labels = {"kind": "Type", "name": "Nom", "units_per_package": "Nombre d'unités dedans",
                  "is_default_purchase": "Conditionnement habituel de commande"}
        help_texts = {"name": "ex : Casier de 12", "units_per_package": "ex : 12 bouteilles dans un casier"}

    def clean_units_per_package(self):
        value = self.cleaned_data["units_per_package"]
        if value < 1:
            raise forms.ValidationError("Au moins 1 unité.")
        return value


class ServingForm(forms.ModelForm):
    class Meta:
        model = ServingOption
        fields = ["name", "base_units", "price_fcfa", "is_active"]
        labels = {"name": "Nom de la portion", "base_units": "Part de bouteille consommée",
                  "price_fcfa": "Prix de la portion (FCFA)", "is_active": "Proposée à la vente"}
        help_texts = {"name": "ex : Verre, Mesure 4 cl",
                      "base_units": "0,2 = un cinquième de bouteille (5 verres par bouteille)."}

    def clean_base_units(self):
        value = self.cleaned_data["base_units"]
        if value <= 0:
            raise forms.ValidationError("Doit être supérieur à 0.")
        return value