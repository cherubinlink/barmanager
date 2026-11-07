from django.contrib import admin

from .models import DailySalesSummary, ProductDailyStat, Recommendation, SalesForecast


class ReadOnlyAdmin(admin.ModelAdmin):
    """Ces données sont calculées : on ne les corrige pas à la main, on relance le calcul."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DailySalesSummary)
class DailySalesSummaryAdmin(ReadOnlyAdmin):
    list_display = ("business_date", "bar", "tickets_count", "revenue_fcfa", "cogs_fcfa", "gross_margin_fcfa",
                    "losses_fcfa", "collected_fcfa", "credit_granted_fcfa", "peak_hour")
    list_filter = ("bar",)
    date_hierarchy = "business_date"


@admin.register(ProductDailyStat)
class ProductDailyStatAdmin(ReadOnlyAdmin):
    list_display = ("business_date", "bar", "product_bar", "qty_sold", "revenue_fcfa", "cogs_fcfa", "qty_lost")
    list_filter = ("bar",)
    search_fields = ("product_bar__product__name",)
    date_hierarchy = "business_date"


@admin.register(SalesForecast)
class SalesForecastAdmin(ReadOnlyAdmin):
    list_display = ("target_start", "bar", "granularity", "product_bar", "predicted_qty", "predicted_revenue_fcfa",
                    "predicted_stockout_date", "suggested_order_qty", "confidence")
    list_filter = ("granularity", "bar", "method")
    search_fields = ("product_bar__product__name",)


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    """Seul le statut est modifiable (par exemple pour rouvrir une recommandation ignorée)."""
    list_display = ("created_at", "bar", "kind", "title", "priority", "status", "generated_by", "valid_until")
    list_filter = ("kind", "status", "generated_by", "bar")
    search_fields = ("title", "message")

    def has_add_permission(self, request):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields if f.name != "status"]