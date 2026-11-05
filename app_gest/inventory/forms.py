from decimal import Decimal

from django import forms
from django.utils import timezone

from catalog.models import ProductBar
from core.models import PeriodType

from .models import LossReport


def _product_field(bar, label="Produit"):
    field = forms.ModelChoiceField(
        label=label, queryset=ProductBar.objects.filter(bar=bar, is_active=True).select_related("product"))
    field.label_from_instance = lambda pb: str(pb.product)
    return field


def _qty_field(label, **kwargs):
    return forms.DecimalField(label=label, min_value=Decimal("0.001"), max_digits=10,
                              decimal_places=3, **kwargs)


class OpeningStockForm(forms.Form):
    """Stock déjà présent au démarrage de l'application (ou oublié) : crée un lot « stock initial »."""

    def __init__(self, *args, bar, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product_bar"] = _product_field(bar)
        self.fields["quantity"] = _qty_field("Quantité en stock (unités)")
        self.fields["unit_cost_fcfa"] = forms.IntegerField(
            label="Prix d'achat d'une unité (FCFA)", min_value=0, required=False,
            help_text="Laissez vide pour utiliser le prix d'achat de la fiche produit.")
        self.fields["since"] = forms.DateField(
            label="Stock présent depuis le", initial=timezone.localdate,
            widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            help_text="Plus la date est ancienne, plus ce stock sera vendu en premier (règle FIFO).")

    def clean_since(self):
        value = self.cleaned_data["since"]
        if value > timezone.localdate():
            raise forms.ValidationError("La date ne peut pas être dans le futur.")
        return value


class AdjustmentForm(forms.Form):
    """Correction manuelle du stock (casse non déclarée, erreur de saisie…)."""

    DIRECTIONS = [("OUT", "Retirer du stock (manquant)"), ("IN", "Ajouter au stock (surplus)")]

    def __init__(self, *args, bar, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product_bar"] = _product_field(bar)
        self.fields["direction"] = forms.ChoiceField(label="Sens", choices=self.DIRECTIONS)
        self.fields["quantity"] = _qty_field("Quantité (unités)")
        self.fields["unit_cost_fcfa"] = forms.IntegerField(
            label="Prix d'achat d'une unité (FCFA)", min_value=0, required=False,
            help_text="Seulement pour un ajout. Vide = prix d'achat de la fiche produit.")
        self.fields["note"] = forms.CharField(
            label="Motif (obligatoire)", max_length=255,
            help_text="Cette correction sera conservée dans le journal des mouvements.")

    def clean_note(self):
        note = self.cleaned_data["note"].strip()
        if len(note) < 5:
            raise forms.ValidationError("Expliquez brièvement le motif (5 caractères minimum).")
        return note


class LossForm(forms.ModelForm):
    class Meta:
        model = LossReport
        fields = ["product_bar", "quantity", "reason", "note", "photo"]
        labels = {"quantity": "Quantité perdue (unités)", "reason": "Motif", "note": "Précisions",
                  "photo": "Photo (facultatif)"}

    def __init__(self, *args, bar, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product_bar"] = _product_field(bar)

    def clean_quantity(self):
        value = self.cleaned_data["quantity"]
        if value <= 0:
            raise forms.ValidationError("La quantité doit être supérieure à 0.")
        return value


class CountCreateForm(forms.Form):
    period_type = forms.ChoiceField(label="Type d'inventaire", choices=PeriodType.choices,
                                    initial=PeriodType.DAY)
    reference_date = forms.DateField(
        label="Date de référence", initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="La période (semaine, mois, trimestre, année) est déduite de cette date.")
    note = forms.CharField(label="Note", required=False, max_length=500)


class CountEntryForm(forms.Form):
    """Un champ par produit : la quantité réellement comptée (laisser vide = pas encore compté)."""

    def __init__(self, *args, count, **kwargs):
        super().__init__(*args, **kwargs)
        for line in count.lines.select_related("product_bar__product__category"):
            field = forms.DecimalField(
                label=str(line.product_bar.product), required=False, min_value=0,
                max_digits=12, decimal_places=3, initial=line.counted_qty)
            field.line = line
            self.fields[f"line_{line.id}"] = field

    def entries(self):
        return {f.line.id: self.cleaned_data.get(name) for name, f in self.fields.items()}


class ClosingForm(forms.Form):
    cash_counted_fcfa = forms.IntegerField(
        label="Espèces comptées dans la caisse (FCFA)", min_value=0, required=False,
        help_text="Comptez l'argent liquide et saisissez le total pour contrôler l'écart.")
    note = forms.CharField(label="Note", required=False, max_length=500)


class ReportForm(forms.Form):
    period = forms.ChoiceField(label="Période", choices=PeriodType.choices, required=False)
    date = forms.DateField(label="Date de référence", required=False,
                           widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))