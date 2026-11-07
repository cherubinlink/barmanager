from django.db import models

# Create your models here.



import uuid
from datetime import time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.utils import timezone

from core.models import PaymentMethod, TimeStampedModel

TRIAL_DAYS = 30


class Plan(TimeStampedModel):
    """Plan d'abonnement : prix fixés par l'administrateur de la plateforme."""

    name = models.CharField("nom", max_length=80)
    code = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    price_fcfa = models.PositiveIntegerField("prix (FCFA)", default=2000)
    duration_days = models.PositiveIntegerField("durée (jours)", default=30)
    max_users = models.PositiveIntegerField(null=True, blank=True)
    features = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "price_fcfa"]

    def __str__(self):
        return f"{self.name} ({self.price_fcfa} FCFA / {self.duration_days} j)"
    
   


class Bar(TimeStampedModel):
    """Compte client (tenant). Un propriétaire peut en posséder plusieurs."""

    # Identifiant PERMANENT encodé dans le QR code (ne change jamais).
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # Code client MODIFIABLE : saisie manuelle / alias du QR.
    client_code = models.CharField(
        "code client", max_length=20, unique=True,
        validators=[RegexValidator(r"^[A-Z0-9_-]{4,20}$", "4 à 20 caractères : A-Z, 0-9, - ou _")],
    )
    name = models.CharField("nom du bar", max_length=150)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_bars"
    )
    phone = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=80, blank=True)
    address = models.CharField(max_length=255, blank=True)
    timezone = models.CharField(max_length=50, default="Africa/Douala")
    # Un bar ouvert après minuit : la « journée » ne change qu'à cette heure.
    business_day_cutoff = models.TimeField(default=time(5, 0))
    qr_ordering_enabled = models.BooleanField("commande par QR", default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} [{self.client_code}]"

    def save(self, *args, **kwargs):
        self.client_code = (self.client_code or "").upper()
        super().save(*args, **kwargs)

    def current_business_date(self, at=None):
        now = (at or timezone.now()).astimezone(ZoneInfo(self.timezone))
        if now.time() < self.business_day_cutoff:
            return (now - timedelta(days=1)).date()
        return now.date()


class Subscription(TimeStampedModel):
    class Status(models.TextChoices):
        TRIAL = "TRIAL", "Essai gratuit"
        ACTIVE = "ACTIVE", "Actif"
        EXPIRED = "EXPIRED", "Expiré (lecture seule)"
        SUSPENDED = "SUSPENDED", "Suspendu"

    bar = models.OneToOneField(Bar, on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.TRIAL)
    trial_ends_at = models.DateTimeField()
    current_period_end = models.DateTimeField(null=True, blank=True)

    @classmethod
    def start_trial(cls, bar):
        return cls.objects.create(bar=bar, trial_ends_at=timezone.now() + timedelta(days=TRIAL_DAYS))

    @property
    def ends_at(self):
        return self.current_period_end or self.trial_ends_at

    @property
    def days_left(self):
        return max((self.ends_at - timezone.now()).days, 0)

    def refresh_status(self, save=True):
        if self.status in (self.Status.TRIAL, self.Status.ACTIVE) and timezone.now() > self.ends_at:
            self.status = self.Status.EXPIRED
            if save:
                self.save(update_fields=["status", "updated_at"])
        return self.status

    @property
    def is_read_only(self):
        return self.refresh_status(save=False) in (self.Status.EXPIRED, self.Status.SUSPENDED)

    def __str__(self):
        return f"{self.bar} – {self.status}"


class SubscriptionPayment(TimeStampedModel):
    """Paiement manuel déclaré par le bar, validé par l'administrateur."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "En attente"
        VALIDATED = "VALIDATED", "Validé"
        REJECTED = "REJECTED", "Rejeté"

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="payments")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="+")
    periods = models.PositiveSmallIntegerField("nombre de périodes", default=1)
    amount_fcfa = models.PositiveIntegerField()
    method = models.CharField(max_length=15, choices=PaymentMethod.choices, default=PaymentMethod.MTN_MOMO)
    reference = models.CharField("référence transaction", max_length=80, blank=True)
    proof = models.ImageField("preuve", upload_to="subscription_proofs/", null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    declared_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    validated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    validated_at = models.DateTimeField(null=True, blank=True)
    admin_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @transaction.atomic
    def validate(self, admin_user):
        if self.status != self.Status.PENDING:
            raise ValueError("Paiement déjà traité.")
        sub = self.subscription
        start = max(timezone.now(), sub.ends_at)
        sub.current_period_end = start + timedelta(days=self.plan.duration_days * self.periods)
        sub.plan, sub.status = self.plan, Subscription.Status.ACTIVE
        sub.save()
        self.status, self.validated_by, self.validated_at = self.Status.VALIDATED, admin_user, timezone.now()
        self.save()

    def reject(self, admin_user, note=""):
        self.status, self.validated_by, self.validated_at, self.admin_note = (
            self.Status.REJECTED, admin_user, timezone.now(), note)
        self.save()
