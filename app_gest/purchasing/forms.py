from datetime import timedelta

from django import forms
from django.utils import timezone

from catalog.models import PackagingUnit, ProductBar

from .models import PurchaseOrder, PurchaseOrderLine, Supplier, SupplierPayment


def _date(label, required=True, initial=None):
    return forms.DateField(label=label, required=required, initial=initial,
                           widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact_name", "phone", "email", "address", "notes", "is_active"]
        labels = {"name": "Nom du fournisseur / dépôt", "contact_name": "Personne à contacter",
                  "phone": "Téléphone", "email": "E-mail", "address": "Adresse", "notes": "Notes",
                  "is_active": "Fournisseur actif"}
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, show_active=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not show_active:
            del self.fields["is_active"]


class OrderForm(forms.ModelForm):
    ordered_at = _date("Date de la commande", initial=timezone.localdate)
    expected_at = _date("Livraison prévue le", required=False)
    due_date = _date("Échéance de paiement", required=False)

    class Meta:
        model = PurchaseOrder
        fields = ["supplier", "ordered_at", "expected_at", "on_credit", "due_date", "notes"]
        labels = {"supplier": "Fournisseur", "on_credit": "Commande à crédit (payée plus tard)",
                  "notes": "Notes"}
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, bar, **kwargs):
        super().__init__(*args, **kwargs)
        suppliers = Supplier.objects.filter(bar=bar, is_active=True)
        if self.instance.pk:
            suppliers = Supplier.objects.filter(bar=bar).filter(pk=self.instance.supplier_id) | suppliers
        self.fields["supplier"].queryset = suppliers.distinct()
        if self.instance.pk and self.instance.status != PurchaseOrder.Status.DRAFT:
            self.fields["supplier"].disabled = True      # fournisseur et date figés après envoi
            self.fields["ordered_at"].disabled = True

    def clean(self):
        data = super().clean()
        ordered, expected = data.get("ordered_at"), data.get("expected_at")
        if data.get("on_credit"):
            if not data.get("due_date"):
                self.add_error("due_date", "Indiquez l'échéance : la commande est à crédit.")
        else:
            data["due_date"] = None
        if ordered and expected and expected < ordered:
            self.add_error("expected_at", "La livraison ne peut pas précéder la commande.")
        return data


class LineForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrderLine
        fields = ["product_bar", "packaging", "quantity_packages", "units_per_package", "package_cost_fcfa"]
        labels = {"product_bar": "Produit", "packaging": "Conditionnement",
                  "quantity_packages": "Nombre de conditionnements commandés",
                  "units_per_package": "Unités par conditionnement",
                  "package_cost_fcfa": "Prix d'un conditionnement (FCFA)"}
        help_texts = {
            "packaging": "Casier, carton, palette… défini sur la fiche du produit (facultatif).",
            "units_per_package": "Seulement si vous n'avez pas choisi de conditionnement.",
            "package_cost_fcfa": "Laissez vide pour utiliser le prix d'achat du produit × unités.",
        }

    def __init__(self, *args, bar, order, **kwargs):
        super().__init__(*args, **kwargs)
        self.order = order
        self.fields["product_bar"].queryset = ProductBar.objects.filter(
            bar=bar, is_active=True).select_related("product")
        self.fields["product_bar"].label_from_instance = lambda pb: f"{pb.product}"
        self.fields["packaging"].queryset = PackagingUnit.objects.filter(bar=bar).select_related("product_bar__product")
        self.fields["packaging"].label_from_instance = lambda p: f"{p.product_bar.product} · {p.name}"
        self.fields["packaging"].required = False
        self.fields["units_per_package"].required = False
        self.fields["package_cost_fcfa"].required = False
        self.fields["quantity_packages"].min_value = 1
        self.fields["quantity_packages"].widget.attrs["min"] = 1

    def clean_quantity_packages(self):
        value = self.cleaned_data["quantity_packages"]
        if value < 1:
            raise forms.ValidationError("Au moins 1.")
        return value

    def clean(self):
        data = super().clean()
        product, packaging = data.get("product_bar"), data.get("packaging")
        if packaging and product and packaging.product_bar_id != product.id:
            self.add_error("packaging", "Ce conditionnement appartient à un autre produit.")
            return data
        units = packaging.units_per_package if packaging else data.get("units_per_package")
        if product and not units:
            self.add_error("units_per_package", "Choisissez un conditionnement ou indiquez les unités par conditionnement.")
        if product and units:
            data["units_per_package"] = units
            duplicate = (self.order.lines.filter(product_bar=product, units_per_package=units)
                         .exclude(pk=self.instance.pk))
            if duplicate.exists():
                raise forms.ValidationError("Ce produit est déjà dans la commande avec ce conditionnement : "
                                            "modifiez la ligne existante.")
            if not data.get("package_cost_fcfa"):
                default = product.purchase_price_fcfa * units
                if default:
                    data["package_cost_fcfa"] = default
                else:
                    self.add_error("package_cost_fcfa", "Indiquez le prix du conditionnement.")
        return data


class PaymentForm(forms.ModelForm):
    paid_at = forms.DateTimeField(
        label="Date du paiement", initial=timezone.now,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"))

    class Meta:
        model = SupplierPayment
        fields = ["amount_fcfa", "method", "paid_at", "reference", "note"]
        labels = {"amount_fcfa": "Montant payé (FCFA)", "method": "Moyen de paiement",
                  "reference": "Référence (n° de transaction, reçu…)", "note": "Note"}

    def __init__(self, *args, order, **kwargs):
        super().__init__(*args, **kwargs)
        self.order = order
        self.fields["amount_fcfa"].initial = max(order.balance_due_fcfa, 0)

    def clean_amount_fcfa(self):
        value = self.cleaned_data["amount_fcfa"]
        if value <= 0:
            raise forms.ValidationError("Le montant doit être supérieur à 0.")
        if value > self.order.balance_due_fcfa:
            raise forms.ValidationError(
                f"Le montant dépasse le solde restant à payer ({self.order.balance_due_fcfa} FCFA).")
        return value

    def clean_paid_at(self):
        value = self.cleaned_data["paid_at"]
        if value > timezone.now() + timedelta(minutes=5):
            raise forms.ValidationError("La date ne peut pas être dans le futur.")
        return value


class ReceiveForm(forms.Form):
    """Un champ par ligne : combien de conditionnements reçoit-on MAINTENANT (réception partielle possible)."""

    def __init__(self, *args, order, **kwargs):
        super().__init__(*args, **kwargs)
        self.quantities = {}
        for line in order.lines.select_related("product_bar__product"):
            remaining = line.quantity_packages - line.received_packages
            if remaining <= 0:
                continue
            field = forms.IntegerField(
                label=str(line.product_bar.product), min_value=0, max_value=remaining,
                initial=remaining, required=False,
                widget=forms.NumberInput(attrs={"min": 0, "max": remaining, "style": "width:6rem"}))
            field.line, field.remaining = line, remaining
            self.fields[f"line_{line.id}"] = field

    def clean(self):
        data = super().clean()
        self.quantities = {f.line.id: data.get(name) for name, f in self.fields.items() if data.get(name)}
        if not self.errors and not self.quantities:
            raise forms.ValidationError("Indiquez au moins une quantité reçue.")
        return data