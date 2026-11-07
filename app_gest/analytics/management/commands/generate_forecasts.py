from django.core.management.base import BaseCommand

from analytics.services import generate_forecasts
from tenants.models import Bar


class Command(BaseCommand):
    help = "Recalcule les prévisions de ventes et de rupture (à lancer après build_daily_stats)."

    def handle(self, *args, **options):
        for bar in Bar.objects.filter(is_active=True):
            count = generate_forecasts(bar)
            self.stdout.write(f"{bar} : {count} prévision(s)." if count
                              else f"{bar} : pas assez d'historique (14 jours de ventes minimum).")
        self.stdout.write(self.style.SUCCESS("Prévisions à jour."))