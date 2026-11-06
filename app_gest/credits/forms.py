from django import forms

from core.models import PaymentMethod
from sales.models import Customer

from .models import PaymentReminder


def _date_widget():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class CreditCreateForm(forms.Form):
    """Créance saisie à la main (dette antérieure, avance…). Les créances de vente se créent seules."""

    amount_fcfa = forms.IntegerField(label="Montant dû (FCFA)", min_value=1)
    due_date = forms.DateField(label="Échéance", required=False, widget=_date_widget(),
                               help_text="Laissez vide s'il n'y a pas de date limite.")
    note = forms.CharField(label="Note", max_length=255, required=False)

    def __init__(self, *args, bar, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"] = forms.ModelChoiceField(
            label="Client", queryset=Customer.objects.filter(bar=bar, is_active=True))
        self.order_fields(["customer", "amount_fcfa", "due_date", "note"])


class CreditPaymentForm(forms.Form):
    amount_fcfa = forms.IntegerField(label="Montant encaissé (FCFA)", min_value=1)
    method = forms.ChoiceField(label="Moyen de paiement", choices=PaymentMethod.choices,
                               initial=PaymentMethod.CASH)
    reference = forms.CharField(label="Référence (Mobile Money…)", max_length=80, required=False)


class DueDateForm(forms.Form):
    due_date = forms.DateField(label="Nouvelle échéance", widget=_date_widget())


class WriteOffForm(forms.Form):
    reason = forms.CharField(label="Motif (obligatoire)", min_length=5, max_length=150)


class ReminderForm(forms.Form):
    channel = forms.ChoiceField(label="Canal", choices=PaymentReminder.Channel.choices,
                                initial=PaymentReminder.Channel.WHATSAPP)
    message = forms.CharField(label="Message (facultatif)", max_length=255, required=False)