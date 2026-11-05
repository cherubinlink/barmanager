from django.apps import apps
from django.core.management.base import BaseCommand

from accounts.permissions import Perm
from tenants.models import Subscription


class Command(BaseCommand):
    help = "Passe les abonnements échus en « expiré » et prévient les gérants (J-7, J-3, jour J)."

    def handle(self, *args, **options):
        use_notifications = apps.is_installed("notifications")
        if use_notifications:
            from notifications.models import Notification, NotificationType
            from notifications.services import notify_bar

        def alert(sub, key, title, level):
            if not use_notifications:
                return
            if Notification.objects.filter(bar=sub.bar, dedup_key=key).exists():
                return                                   # déjà prévenu pour cette échéance
            notify_bar(sub.bar, type=NotificationType.SUBSCRIPTION_TRIAL_ENDING, title=title,
                       perm=Perm.SUBSCRIPTION_MANAGE, level=level, url="/abonnement/", dedup_key=key)

        expired = warned = 0
        subscriptions = Subscription.objects.filter(
            status__in=[Subscription.Status.TRIAL, Subscription.Status.ACTIVE]).select_related("bar")
        for sub in subscriptions:
            was = sub.status
            sub.refresh_status()
            if sub.status == Subscription.Status.EXPIRED:
                expired += 1
                alert(sub, f"sub-expired:{sub.bar_id}:{sub.ends_at:%Y%m%d}",
                      "Abonnement expiré : votre bar est en lecture seule", Notification.Level.CRITICAL
                      if use_notifications else None)
            elif sub.days_left in (7, 3, 0):
                warned += 1
                label = "L'essai gratuit" if was == Subscription.Status.TRIAL else "L'abonnement"
                when = "se termine aujourd'hui" if sub.days_left == 0 else f"se termine dans {sub.days_left} jours"
                alert(sub, f"sub-ending:{sub.bar_id}:{sub.ends_at:%Y%m%d}:{sub.days_left}",
                      f"{label} {when}", Notification.Level.WARNING if use_notifications else None)
        self.stdout.write(self.style.SUCCESS(f"{expired} expiré(s), {warned} rappel(s) envoyé(s)."))