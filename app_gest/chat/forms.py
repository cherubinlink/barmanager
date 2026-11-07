import os

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model

from accounts.models import BarMembership
from catalog.models import ProductBar
from sales.models import Ticket

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".csv"}


def member_queryset(bar, exclude_ids=()):
    ids = BarMembership.objects.filter(bar=bar, is_active=True).values("user_id")
    return get_user_model().objects.filter(pk__in=ids).exclude(pk__in=list(exclude_ids)).order_by("pk")


class GroupForm(forms.Form):
    name = forms.CharField(label="Nom du groupe", max_length=100)

    def __init__(self, *args, bar, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["members"] = forms.ModelMultipleChoiceField(
            label="Participants", queryset=member_queryset(bar, [user.id]), widget=forms.CheckboxSelectMultiple)


class RenameForm(forms.Form):
    name = forms.CharField(label="Nom du groupe", max_length=100)


class AddParticipantsForm(forms.Form):
    """Propose les membres du bar qui ne sont pas déjà dans le groupe."""

    def __init__(self, *args, bar, conversation, **kwargs):
        super().__init__(*args, **kwargs)
        current = conversation.participants.filter(left_at__isnull=True).values_list("user_id", flat=True)
        self.fields["members"] = forms.ModelMultipleChoiceField(
            label="Ajouter", queryset=member_queryset(bar, current), widget=forms.CheckboxSelectMultiple)


class DirectForm(forms.Form):
    user_id = forms.IntegerField(min_value=1)


class EditMessageForm(forms.Form):
    body = forms.CharField(max_length=4000)


class MessageForm(forms.Form):
    """Envoi par HTTP : texte, pièce jointe, ticket ou produit partagé. client_uuid évite les doublons."""

    body = forms.CharField(required=False, max_length=4000)
    attachment = forms.FileField(required=False)
    client_uuid = forms.UUIDField(required=False)
    reply_to_id = forms.IntegerField(required=False, min_value=1)
    ticket_id = forms.IntegerField(required=False, min_value=1)
    product_id = forms.IntegerField(required=False, min_value=1)

    def __init__(self, *args, bar, **kwargs):
        super().__init__(*args, **kwargs)
        self.bar = bar

    def clean_attachment(self):
        f = self.cleaned_data.get("attachment")
        if not f:
            return f
        if os.path.splitext(f.name)[1].lower() not in ALLOWED_EXTENSIONS:
            raise forms.ValidationError("Type de fichier non autorisé (images, PDF, Word, Excel, texte).")
        limit = getattr(settings, "CHAT_MAX_UPLOAD_MB", 10)
        if f.size > limit * 1024 * 1024:
            raise forms.ValidationError(f"Fichier trop lourd ({limit} Mo maximum).")
        return f

    def clean(self):
        d = super().clean()
        if d.get("ticket_id") and not Ticket.objects.filter(bar=self.bar, pk=d["ticket_id"]).exists():
            self.add_error("ticket_id", "Ticket introuvable dans ce bar.")
        if d.get("product_id") and not ProductBar.objects.filter(bar=self.bar, pk=d["product_id"]).exists():
            self.add_error("product_id", "Produit introuvable dans ce bar.")
        if not (d.get("body") or d.get("attachment") or d.get("ticket_id") or d.get("product_id")):
            raise forms.ValidationError("Message vide.")
        return d