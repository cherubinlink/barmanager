from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.realtime import send_to_user

from notifications.models import (Notification, NotificationPreference, NotificationType,
                                  PlatformAnnouncement, PushSubscription)


def _is_enabled(user, bar, ntype, channel="in_app") -> bool:
    pref = NotificationPreference.objects.filter(user=user, bar=bar, type=ntype).first()
    if pref is None:
        return channel == "in_app"
    if pref.muted_until and pref.muted_until > timezone.now():
        return False
    return getattr(pref, channel)


def serialize(n: Notification) -> dict:
    return {
        "id": n.id, "type": n.type, "level": n.level, "title": n.title, "body": n.body,
        "url": n.url, "data": n.data, "occurrences": n.occurrences,
        "bar_id": n.bar_id, "created_at": n.created_at.isoformat(), "is_read": n.is_read,
    }


def notify(*, recipient, type, title, body="", bar=None, level=Notification.Level.INFO,
           url="", data=None, target=None, dedup_key=""):
    """Crée la notification en base puis la pousse en temps réel (WebSocket)."""
    if not _is_enabled(recipient, bar, type):
        return None
    notif = None
    if dedup_key:
        notif = Notification.objects.filter(recipient=recipient, dedup_key=dedup_key, is_read=False).first()
        if notif:
            notif.occurrences += 1
            notif.title, notif.body, notif.data = title, body, data or {}
            notif.save(update_fields=["occurrences", "title", "body", "data", "updated_at"])
    if notif is None:
        extra = {}
        if target is not None:
            extra = {"target_content_type": ContentType.objects.get_for_model(target), "target_id": str(target.pk)}
        notif = Notification.objects.create(
            recipient=recipient, bar=bar, type=type, level=level, title=title, body=body,
            url=url, data=data or {}, dedup_key=dedup_key, **extra,
        )
    transaction.on_commit(lambda: send_to_user(recipient.id, "notification.new", {"notification": serialize(notif)}))
    return notif


def notify_bar(bar, *, type, title, perm=None, exclude_user=None, **kwargs):
    """Notifie les membres actifs d'un bar, éventuellement filtrés par permission."""
    from accounts.models import BarMembership

    sent = []
    for m in BarMembership.objects.filter(bar=bar, is_active=True).select_related("user", "role"):
        if exclude_user is not None and m.user_id == exclude_user.id:
            continue
        if perm and not m.has_perm(perm):
            continue
        n = notify(recipient=m.user, bar=bar, type=type, title=title, **kwargs)
        if n:
            sent.append(n)
    return sent


def mark_read(user, ids=None, dedup_key=None):
    qs = Notification.objects.filter(recipient=user, is_read=False)
    if ids is not None:
        qs = qs.filter(id__in=ids)
    if dedup_key:
        qs = qs.filter(dedup_key=dedup_key)
    return qs.update(is_read=True, read_at=timezone.now())


def visible(user, bar=None):
    """Notifications affichables : non expirées, du bar courant + annonces plateforme (sans bar)."""
    now = timezone.now()
    qs = Notification.objects.filter(recipient=user).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    if bar:
        qs = qs.filter(Q(bar=bar) | Q(bar__isnull=True))
    return qs


def unread_count(user, bar=None) -> int:
    return visible(user, bar).filter(is_read=False).count()


# ------------------------------------------------------------------ préférences
def mute_all(user, bar, hours=None):
    """Met en sourdine tous les types de notification d'un bar (hours=None : réactive)."""
    until = timezone.now() + timedelta(hours=hours) if hours else None
    with transaction.atomic():
        for value in NotificationType.values:
            NotificationPreference.objects.update_or_create(
                user=user, bar=bar, type=value, defaults={"muted_until": until})
    return until


# ------------------------------------------------------------------ annonces plateforme
def due_announcements():
    now = timezone.now()
    return (PlatformAnnouncement.objects.filter(sent=False, publish_at__lte=now)
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)))


@transaction.atomic
def publish_announcement(announcement):
    """Envoie l'annonce à tous les utilisateurs actifs (une seule fois par personne, même multi-bars).
    Retourne le nombre de destinataires."""
    from accounts.models import BarMembership

    announcement = PlatformAnnouncement.objects.select_for_update().get(pk=announcement.pk)
    if announcement.sent:
        return 0
    recipients = {}
    for m in BarMembership.objects.filter(is_active=True).select_related("user", "role"):
        if announcement.only_owners and not m.is_owner:
            continue
        recipients[m.user_id] = m.user
    count = 0
    for user in recipients.values():
        n = notify(recipient=user, type=NotificationType.SYSTEM, title=announcement.title,
                   body=announcement.body[:500], level=announcement.level,
                   dedup_key=f"announce:{announcement.pk}")
        if n:
            count += 1
            if announcement.expires_at:
                n.expires_at = announcement.expires_at
                n.save(update_fields=["expires_at", "updated_at"])
    announcement.sent = True
    announcement.save(update_fields=["sent", "updated_at"])
    return count


# ------------------------------------------------------------------ nettoyage
def purge_notifications(read_days=30):
    """Supprime les notifications lues depuis plus de `read_days` jours, les expirées et les abonnements push inactifs."""
    now = timezone.now()
    old_read = Notification.objects.filter(is_read=True, read_at__lt=now - timedelta(days=read_days)).delete()[0]
    expired = Notification.objects.filter(expires_at__lt=now).delete()[0]
    push = PushSubscription.objects.filter(is_active=False).delete()[0]
    return {"read": old_read, "expired": expired, "push": push}