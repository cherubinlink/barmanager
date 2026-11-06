from django.core.management.base import BaseCommand

from notifications.services import purge_notifications


class Command(BaseCommand):
    help = "Supprime les notifications lues anciennes, les expirées et les abonnements push inactifs."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30, help="Âge minimum (en jours) des notifications lues à supprimer.")

    def handle(self, *args, **options):
        r = purge_notifications(read_days=options["days"])
        self.stdout.write(self.style.SUCCESS(
            f"Supprimé : {r['read']} lue(s), {r['expired']} expirée(s), {r['push']} abonnement(s) push inactif(s)."))