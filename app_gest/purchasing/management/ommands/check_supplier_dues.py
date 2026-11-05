from django.apps import apps
from django.core.management.base import BaseCommand

from accounts.permissions import Perm
from purchasing.models import PurchaseOrder


class Command(BaseCommand):
    help = "Prévient les acheteurs des dettes fournisseurs : à J-3, le jour J, puis chaque semaine de retard."

    def handle(self, *args, **options):
        if not apps.is_installed("notifications"):
            self.stdout.write("L'app notifications n'est pas installée : rien à envoyer.")
            return
        from notifications.models import Notification, NotificationType
        from notifications.services import notify_bar

        owed = (PurchaseOrder.objects.exclude(status__in=(PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.CANCELLED))
                .exclude(payment_status=PurchaseOrder.PaymentStatus.PAID)
                .filter(due_date__isnull=False).select_related("bar", "supplier"))
        sent = 0
        for order in owed:
            today = order.bar.current_business_date()
            days = (order.due_date - today).days
            if days == 3:
                key, level, when = f"supplier-due:{order.id}:j3", Notification.Level.WARNING, "à payer dans 3 jours"
            elif days == 0:
                key, level, when = f"supplier-due:{order.id}:j0", Notification.Level.WARNING, "à payer aujourd'hui"
            elif days < 0:
                key = f"supplier-due:{order.id}:late:{today:%G%V}"
                level, when = Notification.Level.CRITICAL, f"en retard de {-days} jour(s)"
            else:
                continue
            if Notification.objects.filter(bar=order.bar, dedup_key=key).exists():
                continue
            notify_bar(order.bar, type=NotificationType.SUPPLIER_DUE,
                       title=f"{order.supplier.name} : {order.balance_due_fcfa} FCFA {when}",
                       body=f"Commande {order.reference}", perm=Perm.PURCHASE_MANAGE, level=level,
                       url=f"/achats/{order.pk}/", dedup_key=key)
            sent += 1
        self.stdout.write(self.style.SUCCESS(f"{sent} rappel(s) de paiement fournisseur envoyé(s)."))