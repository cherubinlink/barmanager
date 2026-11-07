from django.apps import apps
from django.core.management.base import BaseCommand

from accounts.permissions import Perm
from analytics.services import generate_recommendations
from tenants.models import Bar


class Command(BaseCommand):
    help = "Génère les recommandations (réapprovisionnement, marges, faible rotation, crédits à risque…) et prévient le gérant."

    def handle(self, *args, **options):
        notify_ok = apps.is_installed("notifications")
        for bar in Bar.objects.filter(is_active=True):
            created = generate_recommendations(bar)
            self.stdout.write(f"{bar} : {len(created)} nouvelle(s) recommandation(s).")
            urgent = [r for r in created if r.priority <= 2]
            if urgent and notify_ok:
                from notifications.models import Notification, NotificationType
                from notifications.services import notify_bar
                notify_bar(bar, type=NotificationType.RECOMMENDATION, perm=Perm.REPORT_VIEW,
                           title=f"{len(urgent)} recommandation(s) importante(s)",
                           body=" · ".join(r.title for r in urgent[:3])[:500],
                           level=Notification.Level.WARNING, url="/analytics/recommandations/",
                           dedup_key=f"reco:{bar.id}")
        self.stdout.write(self.style.SUCCESS("Recommandations à jour."))