import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password

from tenants.models import Bar

from accounts.models import User, Role,BarMembership
from accounts.permissions import PERMISSION_GROUPS
from django.utils.text import slugify


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


class MemberAddForm(forms.Form):
    """Le gérant crée le compte d'un employé et lui attribue un rôle."""

    username = forms.CharField(label="Nom d'utilisateur", max_length=150)
    first_name = forms.CharField(label="Prénom", max_length=150)
    last_name = forms.CharField(label="Nom", max_length=150, required=False)
    phone = forms.CharField(label="Téléphone", max_length=20, required=False)
    password = forms.CharField(
        label="Mot de passe provisoire", widget=forms.PasswordInput,
        help_text="Communiquez-le à la personne : elle pourra le changer depuis son profil.")
    role = forms.ModelChoiceField(label="Rôle", queryset=Role.objects.none())

    def __init__(self, *args, bar, **kwargs):
        super().__init__(*args, **kwargs)
        self.bar = bar
        self.fields["role"].queryset = Role.objects.filter(bar=bar)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ce nom d'utilisateur est déjà pris.")
        return username

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def save(self, invited_by):
        d = self.cleaned_data
        user = User.objects.create_user(
            username=d["username"], password=d["password"], first_name=d["first_name"],
            last_name=d["last_name"], phone=d["phone"])
        return BarMembership.objects.create(bar=self.bar, user=user, role=d["role"], invited_by=invited_by)


class MemberEditForm(forms.Form):
    role = forms.ModelChoiceField(label="Rôle", queryset=Role.objects.none())
    is_active = forms.BooleanField(label="Actif dans ce bar", required=False)
    new_password = forms.CharField(
        label="Nouveau mot de passe provisoire", required=False, widget=forms.PasswordInput,
        help_text="Laissez vide pour ne rien changer.")

    def __init__(self, *args, membership, can_reset_password, **kwargs):
        super().__init__(*args, **kwargs)
        self.membership = membership
        self.fields["role"].queryset = Role.objects.filter(bar=membership.bar)
        self.initial.update(role=membership.role_id, is_active=membership.is_active)
        if not can_reset_password:
            del self.fields["new_password"]

    def clean_new_password(self):
        password = self.cleaned_data.get("new_password")
        if password:
            validate_password(password, self.membership.user)
        return password

    def save(self):
        m = self.membership
        m.role, m.is_active = self.cleaned_data["role"], self.cleaned_data["is_active"]
        m.save()
        password = self.cleaned_data.get("new_password")
        if password:
            m.user.set_password(password)
            m.user.save(update_fields=["password"])
        return m


def _permission_choices():
    return [(group, list(items)) for group, items in PERMISSION_GROUPS.items()]


class RoleForm(forms.Form):
    name = forms.CharField(label="Nom du rôle", max_length=80)
    permissions = forms.MultipleChoiceField(
        label="Ce que ce rôle peut faire", required=False,
        choices=_permission_choices, widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, bar, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.bar, self.instance = bar, instance
        if instance is not None:
            self.initial.update(name=instance.name, permissions=instance.permissions)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        qs = Role.objects.filter(bar=self.bar, name__iexact=name)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Un rôle porte déjà ce nom.")
        return name

    def save(self):
        name, permissions = self.cleaned_data["name"], self.cleaned_data["permissions"]
        if self.instance is None:
            base = slugify(name)[:36] or "role"
            code, i = base, 2
            while Role.objects.filter(bar=self.bar, code=code).exists():
                code, i = f"{base}-{i}", i + 1
            return Role.objects.create(bar=self.bar, name=name, code=code, permissions=permissions)
        self.instance.name, self.instance.permissions = name, permissions
        self.instance.save()
        return self.instance


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone", "avatar", "language")
        labels = {"first_name": "Prénom", "last_name": "Nom", "email": "E-mail",
                  "phone": "Téléphone", "avatar": "Photo", "language": "Langue"}