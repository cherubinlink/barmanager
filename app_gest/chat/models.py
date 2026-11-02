import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, Q

from core.models import BarScopedModel, TimeStampedModel


class Conversation(BarScopedModel):
    """Messagerie INTERNE : uniquement entre membres d'un même bar."""

    class Kind(models.TextChoices):
        DIRECT = "DIRECT", "Message privé"
        GROUP = "GROUP", "Groupe"
        CHANNEL = "CHANNEL", "Canal d'équipe"

    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.DIRECT)
    name = models.CharField(max_length=100, blank=True)
    # "min_id:max_id" : garantit une seule conversation privée par paire d'utilisateurs
    direct_key = models.CharField(max_length=40, blank=True)
    is_default_channel = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_message_preview = models.CharField(max_length=140, blank=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["-last_message_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["bar", "direct_key"], condition=~Q(direct_key=""), name="uniq_direct_conversation"
            )
        ]

    @staticmethod
    def make_direct_key(user_a_id, user_b_id) -> str:
        lo, hi = sorted([user_a_id, user_b_id])
        return f"{lo}:{hi}"

    @classmethod
    def get_or_create_direct(cls, bar, user_a, user_b):
        key = cls.make_direct_key(user_a.id, user_b.id)
        conv, created = cls.objects.get_or_create(
            bar=bar, direct_key=key, defaults={"kind": cls.Kind.DIRECT, "created_by": user_a}
        )
        if created:
            for u in (user_a, user_b):
                ConversationParticipant.objects.create(conversation=conv, user=u)
        return conv

    def __str__(self):
        return self.name or f"Conversation {self.pk}"


class ConversationParticipant(TimeStampedModel):
    class Role(models.TextChoices):
        MEMBER = "MEMBER", "Membre"
        ADMIN = "ADMIN", "Administrateur"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversation_links")
    role = models.CharField(max_length=8, choices=Role.choices, default=Role.MEMBER)
    last_read_message = models.ForeignKey("Message", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    last_read_at = models.DateTimeField(null=True, blank=True)
    is_muted = models.BooleanField(default=False)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["conversation", "user"], name="uniq_participant")]

    def clean(self):
        from accounts.models import BarMembership

        ok = BarMembership.objects.filter(
            bar_id=self.conversation.bar_id, user_id=self.user_id, is_active=True
        ).exists()
        if not ok:
            raise ValidationError("Cet utilisateur n'appartient pas à ce bar.")

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.clean()
        super().save(*args, **kwargs)

    def unread_count(self) -> int:
        qs = self.conversation.messages.exclude(sender_id=self.user_id).filter(deleted_at__isnull=True)
        if self.last_read_at:
            qs = qs.filter(created_at__gt=self.last_read_at)
        return qs.count()


class Message(TimeStampedModel):
    class Kind(models.TextChoices):
        TEXT = "TEXT", "Texte"
        IMAGE = "IMAGE", "Image"
        FILE = "FILE", "Fichier"
        SYSTEM = "SYSTEM", "Message système"
        TICKET_REF = "TICKET_REF", "Ticket partagé"
        PRODUCT_REF = "PRODUCT_REF", "Produit partagé"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.TEXT)
    body = models.TextField(blank=True)
    attachment = models.FileField(upload_to="chat/%Y/%m/", null=True, blank=True)
    attachment_name = models.CharField(max_length=150, blank=True)
    reply_to = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="replies")
    # Cartes « métier » : partager un ticket ou un produit dans la discussion
    related_ticket = models.ForeignKey("sales.Ticket", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    related_product = models.ForeignKey("catalog.ProductBar", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # Généré côté client : évite les doublons en cas de renvoi (réseau instable)
    client_uuid = models.UUIDField(default=uuid.uuid4)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["conversation", "-created_at"])]
        constraints = [
            models.UniqueConstraint(fields=["conversation", "sender", "client_uuid"], name="uniq_message_client_uuid")
        ]

    def __str__(self):
        return f"{self.sender_id}: {self.body[:30]}"


class MessageReceipt(models.Model):
    """Accusés de réception/lecture (utile surtout pour les messages privés)."""

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="receipts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["message", "user"], name="uniq_receipt")]


class UserPresence(TimeStampedModel):
    class Status(models.TextChoices):
        ONLINE = "ONLINE", "En ligne"
        AWAY = "AWAY", "Absent"
        OFFLINE = "OFFLINE", "Hors ligne"

    bar = models.ForeignKey("tenants.Bar", on_delete=models.CASCADE, related_name="presences")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="presences")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OFFLINE)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bar", "user"], name="uniq_presence")]
