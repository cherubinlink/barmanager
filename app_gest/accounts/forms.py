import re

from django import forms
from django.contrib.auth.forms import UserCreationForm

from tenants.models import Bar

from accounts.models import User


class BarFieldsMixin(forms.Form):
    bar_name = forms.CharField(label="Nom du bar", max_length=150)
    client_code = forms.CharField(
        label="Code client du bar", max_length=20,
        help_text="4 à 20 caractères : lettres, chiffres, - ou _ (ex : CHEZPAUL).",
    )
    city = forms.CharField(label="Ville", max_length=80, required=False)

    def clean_client_code(self):
        code = self.cleaned_data["client_code"].strip().upper()
        if not re.fullmatch(r"[A-Z0-9_-]{4,20}", code):
            raise forms.ValidationError("4 à 20 caractères : lettres, chiffres, - ou _.")
        if Bar.objects.filter(client_code=code).exists():
            raise forms.ValidationError("Ce code est déjà utilisé, choisissez-en un autre.")
        return code


class BarForm(BarFieldsMixin):
    pass


class RegisterForm(BarFieldsMixin, UserCreationForm):
    field_order = ["username", "first_name", "last_name", "phone", "email",
                   "password1", "password2", "bar_name", "client_code", "city"]

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "phone", "email")