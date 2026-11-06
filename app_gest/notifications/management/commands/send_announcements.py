from django.core.management.base import BaseCommand

from notifications.services import due_announcements, publish_announcement


class Command(BaseCommand):
    help = "Envoie les annonces plateforme dont la date de publication est arrivée (à planifier toutes les 5 minutes)."

    def handle(self, *args, **options):
        announcements = list(due_announcements())
        total = 0
        for announcement in announcements:
            total += publish_announcement(announcement)
        self.stdout.write(self.style.SUCCESS(
            f"{len(announcements)} annonce(s) publiée(s), {total} notification(s) envoyée(s)."))