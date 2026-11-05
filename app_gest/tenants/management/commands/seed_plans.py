from django.core.management.base import BaseCommand

from tenants.models import Plan
from tenants.plans import PLAN_CATALOG, feature_flags


class Command(BaseCommand):
    help = "Crée ou met à jour les formules d'abonnement : Starter, Business, Premium, Enterprise."

    def handle(self, *args, **options):
        for item in PLAN_CATALOG:
            plan, created = Plan.objects.update_or_create(
                name=item["name"],
                defaults={
                    "price_fcfa": item["price_fcfa"],
                    "max_users": item["max_users"],
                    "description": item["description"],
                    "features": feature_flags(item["features"]),
                    "is_active": True,
                    # Ajoutez ici vos autres champs obligatoires, par exemple la durée : "duration_days": 30,
                },
            )
            self.stdout.write(f"{'Créée' if created else 'Mise à jour'} : {plan.name} ({plan.price_fcfa} FCFA)")
        self.stdout.write(self.style.SUCCESS("Formules à jour."))