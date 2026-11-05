from datetime import timedelta

from django.apps import apps
from django.core.management.base import BaseCommand

from accounts.models import BarMembership
from accounts.permissions import Perm
from inventory.models import DailyClosing
from tenants.models import Bar


class Command(BaseCommand):
    help = "Rappelle de clôturer la journée de la veille (si le bar a vendu quelque chose et ne l'a pas clôturée)."

    def handle(self, *args, **options):
        if not apps.is_installed("notifications"):
            self.stdout.write("L'app notifications n'est pas installée : rien à envoyer.")
            return
        from notifications.models import Notification, NotificationType
        from notifications.services import notify
        from sales.models import Ticket

        sent = 0
        for bar in Bar.objects.filter(is_active=True):
            day = bar.current_business_date() - timedelta(days=1)
            if DailyClosing.objects.filter(bar=bar, business_date=day).exists():
                continue
            if not Ticket.objects.filter(bar=bar, business_date=day).exists():
                continue                                    # aucun ticket ce jour-là : rien à clôturer
            key = f"closing:{bar.id}:{day:%Y%m%d}"
            if Notification.objects.filter(bar=bar, dedup_key=key).exists():
                continue
            for m in BarMembership.objects.filter(bar=bar, is_active=True).select_related("user", "role"):
                if m.has_perm(Perm.POS_FINALIZE) or m.has_perm(Perm.STOCK_ADJUST):
                    notify(recipient=m.user, bar=bar, type=NotificationType.CLOSING_REMINDER,
                           title=f"La journée du {day:%d/%m/%Y} n'est pas clôturée",
                           level=Notification.Level.WARNING, url="/stock/clotures/cloturer/",
                           data={"date": day.isoformat()}, dedup_key=key)
                    sent += 1
        self.stdout.write(self.style.SUCCESS(f"{sent} rappel(s) de clôture envoyé(s)."))