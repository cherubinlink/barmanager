from decimal import Decimal

from django import forms

from catalog.models import ProductBar, ServingOption
from core.models import PaymentMethod

from .models import Customer, Ticket


def _product_field(bar, label="Produit"):
    field = forms.ModelChoiceField(
        label=label, queryset=ProductBar.objects.filter(bar=bar, is_active=True).select_related("product"))
    field.label_from_instance = lambda pb: str(pb.product)
    return field


def _reason_field(label="Motif (obligatoire)", min_len=3):
    return forms.CharField(label=label, max_length=255, min_length=min_len)


class TicketCreateForm(forms.Form):
    custom_name = forms.CharField(label="Nom du client (facultatif)", max_length=80, required=False)
    table_label = forms.CharField(label="Table", max_length=20, required=False)
    payment_timing = forms.ChoiceField(label="Paiement", choices=Ticket.PaymentTiming.choices,
                                       initial=Ticket.PaymentTiming.DEFERRED)
    note = forms.CharField(label="Note", max_length=255, required=False)

    def __init__(self, *args, bar, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"] = forms.ModelChoiceField(
            label="Client identifié (pour le crédit)", required=False,
            queryset=Customer.objects.filter(bar=bar, is_active=True))


class LineForm(forms.Form):
    quantity = forms.DecimalField(label="Quantité", min_value=Decimal("0.01"), max_digits=8,
                                  decimal_places=2, initial=1)

    def __init__(self, *args, bar, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product_bar"] = _product_field(bar)
        self.fields["serving"] = forms.ModelChoiceField(
            label="Format", required=False, empty_label="Unité",
            queryset=ServingOption.objects.filter(product_bar__bar=bar))
        self.order_fields(["product_bar", "serving", "quantity"])

    def clean(self):
        data = super().clean()
        pb, serving = data.get("product_bar"), data.get("serving")
        if pb and serving and serving.product_bar_id != pb.id:
            self.add_error("serving", "Ce format n'appartient pas à ce produit.")
        return data


class VoidLineForm(forms.Form):
    reason = _reason_field()


class DiscountForm(forms.Form):
    discount_fcfa = forms.IntegerField(label="Remise (FCFA)", min_value=0)


class PaymentForm(forms.Form):
    amount_fcfa = forms.IntegerField(label="Montant encaissé (FCFA)", min_value=1)
    method = forms.ChoiceField(label="Moyen de paiement", choices=PaymentMethod.choices,
                               initial=PaymentMethod.CASH)
    reference = forms.CharField(label="Référence (Mobile Money…)", max_length=80, required=False)


class RefundForm(forms.Form):
    amount_fcfa = forms.IntegerField(label="Montant remboursé (FCFA)", min_value=1)
    method = forms.ChoiceField(label="Moyen de remboursement", choices=PaymentMethod.choices,
                               initial=PaymentMethod.CASH)
    justification = _reason_field("Motif du remboursement", min_len=5)


class CancelForm(forms.Form):
    reason = _reason_field()


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone", "credit_limit_fcfa", "notes", "is_active"]
        labels = {"name": "Nom", "phone": "Téléphone", "credit_limit_fcfa": "Plafond de crédit (FCFA)",
                  "notes": "Notes", "is_active": "Actif"}