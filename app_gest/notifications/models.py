from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q

from core.models import TimeStampedModel


class NotificationType(models.TextChoices):
    CHAT_MESSAGE = "CHAT_MESSAGE", "Nouveau message"
    TICKET_QR_NEW = "TICKET_QR_NEW", "Nouvelle commande QR à valider"
    TICKET_PAID = "TICKET_PAID", "Ticket payé"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED", "Paiement reçu"
    LOW_STOCK = "LOW_STOCK", "Stock bas"
    STOCK_OUT = "STOCK_OUT", "Rupture de stock"
    LOSS_DECLARED = "LOSS_DECLARED", "Perte déclarée (à valider)"
    LOSS_REVIEWED = "LOSS_REVIEWED", "Perte validée / rejetée"
    CREDIT_DUE = "CREDIT_DUE", "Créance client échue"
    SUPPLIER_DUE = "SUPPLIER_DUE", "Dette fournisseur à échéance"
    PURCHASE_RECEIVED = "PURCHASE_RECEIVED", "Commande fournisseur reçue"
    INVENTORY_GAP = "INVENTORY_GAP", "Écart d'inventaire"
    CLOSING_REMINDER = "CLOSING_REMINDER", "Clôture du jour à faire"
    RECOMMENDATION = "RECOMMENDATION", "Nouvelle recommandation"
    MEMBER_ADDED = "MEMBER_ADDED", "Nouveau membre dans l'équipe"
    SUBSCRIPTION_TRIAL_ENDING = "SUB_TRIAL_ENDING", "Fin d'essai proche"
    SUBSCRIPTION_EXPIRED = "SUB_EXPIRED", "Abonnement expiré"
    SUBSCRIPTION_PAYMENT = "SUB_PAYMENT", "Paiement d'abonnement traité"
    SYSTEM = "SYSTEM", "Annonce plateforme"


class Notification(TimeStampedModel):
    class Level(models.TextChoices):
        INFO = "INFO", "Information"
        SUCCESS = "SUCCESS", "Succès"
        WARNING = "WARNING", "Attention"
        CRITICAL = "CRITICAL", "Critique"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    # nullable : les annonces plateforme n'appartiennent à aucun bar
    bar = models.ForeignKey("tenants.Bar", null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    type = models.CharField(max_length=20, choices=NotificationType.choices)
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    title = models.CharField(max_length=150)
    body = models.CharField(max_length=500, blank=True)
    url = models.CharField(max_length=255, blank=True, help_text="Lien interne à ouvrir au clic")
    data = models.JSONField(default=dict, blank=True)

    target_content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    target_id = models.CharField(max_length=40, blank=True)
    target = GenericForeignKey("target_content_type", "target_id")

    # Regroupe les répétitions (ex: 1 seule notif « stock bas » non lue par produit).
    dedup_key = models.CharField(max_length=120, blank=True)
    occurrences = models.PositiveIntegerField(default=1)

    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read", "-created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "dedup_key"],
                condition=Q(is_read=False) & ~Q(dedup_key=""),
                name="uniq_unread_dedup_per_recipient",
            )
        ]

    def __str__(self):
        return f"[{self.type}] {self.title} → {self.recipient}"


class NotificationPreference(TimeStampedModel):
    """Par utilisateur, par bar et par type : choisir les canaux (par défaut : in-app actif)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_prefs")
    bar = models.ForeignKey("tenants.Bar", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    type = models.CharField(max_length=20, choices=NotificationType.choices)
    in_app = models.BooleanField(default=True)
    push = models.BooleanField(default=True)
    sms = models.BooleanField(default=False)
    email = models.BooleanField(default=False)
    muted_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "bar", "type"], name="uniq_notification_pref")]


class PushSubscription(TimeStampedModel):
    """Web Push (PWA) : notifier même quand l'application est fermée."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)


class PlatformAnnouncement(TimeStampedModel):
    """Annonce de l'administrateur vers tous les bars (maintenance, nouveautés, promos)."""

    title = models.CharField(max_length=150)
    body = models.TextField()
    level = models.CharField(max_length=10, choices=Notification.Level.choices, default=Notification.Level.INFO)
    publish_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    only_owners = models.BooleanField(default=False)
    sent = models.BooleanField(default=False)
