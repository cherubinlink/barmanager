from django.core.management.base import BaseCommand

from chat.services import sync_default_channel_members
from tenants.models import Bar


class Command(BaseCommand):
    help = "Crée le canal « Équipe » de chaque bar et y inscrit tous les membres actifs (rattrapage)."

    def handle(self, *args, **options):
        added = 0
        for bar in Bar.objects.filter(is_active=True):
            added += sync_default_channel_members(bar)
        self.stdout.write(self.style.SUCCESS(f"{added} inscription(s) au canal d'équipe."))