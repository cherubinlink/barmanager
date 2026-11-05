from django.db.models import Q

from .models import ProductGlobal, ProductPriceHistory


def record_price(product_bar, user):
    """Garde une trace de chaque changement de prix (historique par bar)."""
    return ProductPriceHistory.objects.create(
        bar=product_bar.bar, product_bar=product_bar,
        sale_price_fcfa=product_bar.sale_price_fcfa,
        purchase_price_fcfa=product_bar.purchase_price_fcfa,
        effective_from=product_bar.price_effective_from, changed_by=user)


def visible_global_products(bar):
    """Produits du catalogue commun que CE bar peut ajouter : produits validés
    + ses propres propositions en attente de validation."""
    return (ProductGlobal.objects
            .filter(is_active=True, merged_into__isnull=True)
            .filter(Q(status=ProductGlobal.Status.APPROVED)
                    | Q(status=ProductGlobal.Status.PENDING, created_by_bar=bar)))