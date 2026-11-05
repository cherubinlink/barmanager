import re
from zoneinfo import ZoneInfo

from django import forms

from .models import Bar, Plan, SubscriptionPayment

MAX_PROOF_SIZE = 5 * 1024 * 1024  # 5 Mo


class BarSettingsForm(forms.ModelForm):
    client_code = forms.CharField(
        label="Code client", max_length=20,
        help_text="Les clients peuvent le saisir pour trouver votre bar. Les QR codes déjà imprimés "
                  "continuent de fonctionner si vous le changez.")
    business_day_cutoff = forms.TimeField(
        label="Heure de changement de journée",
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
        help_text="Avant cette heure, les ventes comptent pour la veille (bar ouvert après minuit).")

    class Meta:
        model = Bar
        fields = ["name", "client_code", "phone", "city", "address", "timezone",
                  "business_day_cutoff", "qr_ordering_enabled"]
        labels = {"name": "Nom du bar", "phone": "Téléphone", "city": "Ville", "address": "Adresse",
                  "timezone": "Fuseau horaire", "qr_ordering_enabled": "Autoriser la commande par QR code"}

    def clean_client_code(self):
        code = self.cleaned_data["client_code"].strip().upper()
        if not re.fullmatch(r"[A-Z0-9_-]{4,20}", code):
            raise forms.ValidationError("4 à 20 caractères : lettres, chiffres, - ou _.")
        if Bar.objects.filter(client_code=code).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ce code est déjà utilisé, choisissez-en un autre.")
        return code

    def clean_timezone(self):
        value = self.cleaned_data["timezone"].strip()
        try:
            ZoneInfo(value)
        except Exception:
            raise forms.ValidationError("Fuseau horaire inconnu (exemple : Africa/Douala).")
        return value


class PaymentDeclareForm(forms.ModelForm):
    plan = forms.ModelChoiceField(label="Formule", queryset=Plan.objects.filter(is_active=True))
    periods = forms.IntegerField(label="Nombre de périodes", min_value=1, max_value=12, initial=1)
    reference = forms.CharField(
        label="Référence de la transaction", max_length=80,
        help_text="Identifiant du transfert Mobile Money, ou nom de la personne qui a reçu les espèces.")

    class Meta:
        model = SubscriptionPayment
        fields = ["plan", "periods", "method", "reference", "proof"]
        labels = {"method": "Moyen de paiement", "proof": "Capture ou photo du reçu (facultatif)"}

    def clean_proof(self):
        proof = self.cleaned_data.get("proof")
        if proof and proof.size > MAX_PROOF_SIZE:
            raise forms.ValidationError("Image trop lourde (5 Mo maximum).")
        return proof

    def save(self, subscription, user):
        payment = super().save(commit=False)
        payment.subscription = subscription
        payment.amount_fcfa = payment.plan.price_fcfa * payment.periods   # calculé côté serveur
        payment.declared_by = user
        payment.save()
        return payment


class EnterCodeForm(forms.Form):
    client_code = forms.CharField(label="Code du bar", max_length=20)

    def clean_client_code(self):
        code = self.cleaned_data["client_code"].strip().upper()
        bar = Bar.objects.filter(client_code=code, is_active=True).first()
        if bar is None:
            raise forms.ValidationError("Aucun bar ne correspond à ce code.")
        self.bar = bar
        return code