import csv

from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from catalog.models import Category, ProductGlobal, normalize_name


class Command(BaseCommand):
    help = ("Charge le catalogue commun depuis un fichier CSV (séparateur « ; »). "
            "Colonnes : categorie;type;nom;marque;volume_cl;alcool")

    def add_arguments(self, parser):
        parser.add_argument("fichier")

    def handle(self, *args, **options):
        valid_kinds = {k for k, _ in Category.Kind.choices}
        created = skipped = 0
        try:
            handle = open(options["fichier"], encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise CommandError(f"Fichier illisible : {exc}")
        with handle:
            for n, row in enumerate(csv.DictReader(handle, delimiter=";"), start=2):
                name = (row.get("nom") or "").strip()
                kind = (row.get("type") or "OTHER").strip().upper()
                if not name:
                    continue
                if kind not in valid_kinds:
                    raise CommandError(f"Ligne {n} : type « {kind} » inconnu ({', '.join(sorted(valid_kinds))}).")
                cat_name = (row.get("categorie") or kind).strip()
                category, _ = Category.objects.get_or_create(
                    slug=slugify(cat_name), defaults={"name": cat_name, "kind": kind})
                volume = int(row["volume_cl"]) if (row.get("volume_cl") or "").strip() else None
                alcohol = (row.get("alcool") or "").strip().replace(",", ".") or None
                if ProductGlobal.objects.filter(normalized_name=normalize_name(name), volume_cl=volume).exists():
                    skipped += 1
                    continue
                ProductGlobal.objects.create(
                    name=name, brand=(row.get("marque") or "").strip(), category=category,
                    volume_cl=volume, alcohol_percent=alcohol, status=ProductGlobal.Status.APPROVED)
                created += 1
        self.stdout.write(self.style.SUCCESS(f"{created} produit(s) créé(s), {skipped} déjà présent(s)."))