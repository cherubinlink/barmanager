from datetime import timedelta

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db.models import Q, Sum

from accounts.models import BarMembership
from accounts.permissions import Perm
from credits.models import CustomerCredit
from tenants.models import Bar

SOON_DAYS = 3


class Command(BaseCommand):
    help = "Prévient le personnel des créances clients échues ou qui arrivent à échéance (une notification par bar et par jour)."

    def handle(self, *args, **options):
        if not apps.is_installed("notifications"):
            self.stdout.write("L'app notifications n'est pas installée : rien à envoyer.")
            return
        from notifications.models import Notification, NotificationType
        from notifications.services import notify

        sent = 0
        for bar in Bar.objects.filter(is_active=True):
            today = bar.current_business_date()
            due = CustomerCredit.objects.filter(
                bar=bar, status__in=(CustomerCredit.Status.OPEN, CustomerCredit.Status.PARTIAL)).filter(
                Q(due_date__lt=today) | Q(due_date__range=(today, today + timedelta(days=SOON_DAYS))))
            if not due.exists():
                continue
            key = f"credit-due:{bar.id}:{today:%Y%m%d}"
            if Notification.objects.filter(bar=bar, dedup_key=key).exists():
                continue
            agg = due.aggregate(t=Sum("amount_fcfa"), p=Sum("amount_paid_fcfa"))
            amount = (agg["t"] or 0) - (agg["p"] or 0)
            late = due.filter(due_date__lt=today).count()
            body = f"{late} en retard, {due.count() - late} à échéance sous {SOON_DAYS} jours."
            for m in BarMembership.objects.filter(bar=bar, is_active=True).select_related("user", "role"):
                if m.has_perm(Perm.CREDIT_MANAGE):
                    notify(recipient=m.user, bar=bar, type=NotificationType.CREDIT_DUE,
                           title=f"{due.count()} créance(s) à relancer : {amount} FCFA",
                           body=body, level=Notification.Level.WARNING,
                           url="/credits/?state=retard", data={"count": due.count(), "amount": int(amount)},
                           dedup_key=key)
                    sent += 1
        self.stdout.write(self.style.SUCCESS(f"{sent} rappel(s) de créances envoyé(s)."))