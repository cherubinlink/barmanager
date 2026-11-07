from django.core.management.base import BaseCommand

from chat.services import purge_deleted_messages


class Command(BaseCommand):
    help = "Supprime définitivement (base et fichiers) les messages supprimés depuis plus de N jours."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)

    def handle(self, *args, **options):
        n = purge_deleted_messages(options["days"])
        self.stdout.write(self.style.SUCCESS(f"{n} élément(s) supprimé(s)."))