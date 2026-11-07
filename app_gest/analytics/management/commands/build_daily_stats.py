from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from analytics.services import build_range
from tenants.models import Bar


class Command(BaseCommand):
    help = "Calcule les résumés journaliers et les stats produits. Sans option : hier et aujourd'hui, pour tous les bars."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="Dernier jour à calculer (AAAA-MM-JJ). Défaut : aujourd'hui.")
        parser.add_argument("--days", type=int, default=2, help="Nombre de jours à recalculer, en remontant (90 pour un rattrapage).")
        parser.add_argument("--bar", type=int, help="Identifiant d'un bar (défaut : tous les bars actifs).")

    def handle(self, *args, **options):
        try:
            forced_end = date.fromisoformat(options["date"]) if options["date"] else None
        except ValueError:
            raise CommandError("Date invalide : utilisez le format AAAA-MM-JJ.")
        bars = Bar.objects.filter(is_active=True)
        if options["bar"]:
            bars = bars.filter(pk=options["bar"])
        for bar in bars:
            end = forced_end or bar.current_business_date()
            start = end - timedelta(days=max(options["days"], 1) - 1)
            built = build_range(bar, start, end)
            self.stdout.write(f"{bar} : {built} journée(s) enregistrée(s) du {start:%d/%m/%Y} au {end:%d/%m/%Y}.")
        self.stdout.write(self.style.SUCCESS("Statistiques journalières à jour."))