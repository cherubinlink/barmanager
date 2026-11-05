from django.contrib import admin, messages

from .models import Category, ProductBar, ProductGlobal


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ProductGlobal)
class ProductGlobalAdmin(admin.ModelAdmin):
    """Catalogue commun : vous le remplissez, et validez les produits proposés par les bars."""

    list_display = ("name", "brand", "category", "volume_cl", "status", "created_by_bar", "is_active")
    list_filter = ("status", "category", "is_active")
    search_fields = ("name", "brand", "barcode")
    list_editable = ("is_active",)
    actions = ["approve", "reject"]

    @admin.action(description="✅ Valider (visible pour tous les bars)")
    def approve(self, request, queryset):
        n = queryset.update(status=ProductGlobal.Status.APPROVED)
        self.message_user(request, f"{n} produit(s) validé(s).", messages.SUCCESS)

    @admin.action(description="❌ Rejeter (reste utilisable par les bars qui l'ont déjà)")
    def reject(self, request, queryset):
        n = queryset.update(status=ProductGlobal.Status.REJECTED)
        self.message_user(request, f"{n} produit(s) rejeté(s).", messages.WARNING)


@admin.register(ProductBar)
class ProductBarAdmin(admin.ModelAdmin):
    list_display = ("product", "bar", "sale_price_fcfa", "purchase_price_fcfa", "is_active")
    list_filter = ("is_active", "bar")
    search_fields = ("product__name", "bar__name")