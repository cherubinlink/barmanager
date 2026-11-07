from django.core.management.base import BaseCommand

from chat.services import reset_presence


class Command(BaseCommand):
    help = "Remet tout le monde « hors ligne » (à lancer au démarrage du serveur : une coupure brutale laisse des présences périmées)."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(f"{reset_presence()} présence(s) remise(s) à zéro."))