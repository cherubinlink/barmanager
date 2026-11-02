from django.apps import apps
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from .utils import active_memberships

from django.utils import timezone


def current_bar(request):
    ctx = {"site_name": getattr(settings, "SITE_NAME", "BarManager")}
    bar = getattr(request, "bar", None)
    if bar is None:
        return ctx
    ctx.update(bar=bar, membership=request.membership,
               bar_count=active_memberships(request.user).count())
    try:
        subscription = bar.subscription
        subscription.refresh_status()
        ctx["subscription"] = subscription
    except ObjectDoesNotExist:
        pass
    if apps.is_installed("notifications"):
        from notifications.services import unread_count
        ctx["unread_notifications"] = unread_count(request.user, bar)
    return ctx


def subscription_info(subscription):
    """Jours restants et niveau d'alerte (ok, warning, danger)."""
    end = None
    # Adaptez cette liste au vrai nom du champ de fin dans votre modèle Subscription
    for name in ("ends_at", "end_date", "expires_at", "current_period_end", "trial_ends_at"):
        end = getattr(subscription, name, None)
        if end:
            break
    if not end:
        return None
    if hasattr(end, "date"):                       # DateTimeField
        end = timezone.localtime(end).date() if timezone.is_aware(end) else end.date()
    days = (end - timezone.localdate()).days
    label = getattr(subscription, "get_status_display", lambda: "Abonnement")()
    return {"days": max(days, 0), "days_abs": abs(days), "end": end, "label": label,
            "expired": days < 0,
            "level": "danger" if days < 0 else "warning" if days <= 7 else "ok"}