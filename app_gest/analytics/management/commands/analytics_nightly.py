from django.core.management import call_command
from django.core.management.base import BaseCommand

from analytics.services import purge_old


class Command(BaseCommand):
    help = "Tâche de nuit complète : statistiques, prévisions, recommandations, nettoyage. À planifier une fois par nuit."

    def handle(self, *args, **options):
        call_command("build_daily_stats", stdout=self.stdout)
        call_command("generate_forecasts", stdout=self.stdout)
        call_command("generate_recommendations", stdout=self.stdout)
        r = purge_old()
        self.stdout.write(self.style.SUCCESS(
            f"Nettoyage : {r['forecasts']} prévision(s) et {r['recommendations']} recommandation(s) anciennes supprimées."))