from django.apps import apps
from django.core.management.base import BaseCommand

from accounts.models import BarMembership
from accounts.permissions import Perm
from sales.models import Ticket
from tenants.models import Bar

Status = Ticket.Status


class Command(BaseCommand):
    help = "Rappelle de finaliser ou d'annuler les tickets restés ouverts les jours précédents."

    def handle(self, *args, **options):
        if not apps.is_installed("notifications"):
            self.stdout.write("L'app notifications n'est pas installée : rien à envoyer.")
            return
        from notifications.models import Notification, NotificationType
        from notifications.services import notify

        sent = 0
        for bar in Bar.objects.filter(is_active=True):
            today = bar.current_business_date()
            count = Ticket.objects.filter(
                bar=bar, business_date__lt=today,
                status__in=(Status.OPEN, Status.AWAITING_PAYMENT, Status.PENDING_VALIDATION)).count()
            if not count:
                continue
            key = f"open-tickets:{bar.id}:{today:%Y%m%d}"
            if Notification.objects.filter(bar=bar, dedup_key=key).exists():
                continue
            for m in BarMembership.objects.filter(bar=bar, is_active=True).select_related("user", "role"):
                if m.has_perm(Perm.POS_FINALIZE):
                    notify(recipient=m.user, bar=bar, type=NotificationType.CLOSING_REMINDER,
                           title=f"{count} ticket(s) des jours précédents sont encore ouverts",
                           level=Notification.Level.WARNING, url="/sales/?state=OPEN",
                           data={"count": count}, dedup_key=key)
                    sent += 1
        self.stdout.write(self.style.SUCCESS(f"{sent} rappel(s) de tickets envoyé(s)."))