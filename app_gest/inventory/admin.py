from django.contrib import admin

from .models import (DailyClosing, DailyClosingLine, InventoryCount, InventoryCountLine,
                     LossReport, StockLot, StockMovement)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Le journal de stock ne se modifie jamais à la main : on corrige par un mouvement."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyAdmin):
    list_display = ("occurred_at", "bar", "product_bar", "kind", "quantity", "unit_cost_fcfa", "created_by")
    list_filter = ("kind", "bar")
    search_fields = ("product_bar__product__name", "note")
    date_hierarchy = "occurred_at"


@admin.register(StockLot)
class StockLotAdmin(ReadOnlyAdmin):
    list_display = ("id", "bar", "product_bar", "received_at", "initial_qty", "remaining_qty", "unit_cost_fcfa", "status")
    list_filter = ("status", "source", "bar")


@admin.register(LossReport)
class LossReportAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "bar", "product_bar", "quantity", "reason", "status", "declared_by")
    list_filter = ("status", "reason", "bar")


class CountLineInline(admin.TabularInline):
    model = InventoryCountLine
    extra = 0
    can_delete = False
    readonly_fields = ("product_bar", "theoretical_qty", "counted_qty", "unit_cost_fcfa", "adjustment_movement")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(InventoryCount)
class InventoryCountAdmin(ReadOnlyAdmin):
    list_display = ("period_end", "period_type", "bar", "status", "counted_by", "validated_by")
    list_filter = ("status", "period_type", "bar")
    inlines = [CountLineInline]


class ClosingLineInline(admin.TabularInline):
    model = DailyClosingLine
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DailyClosing)
class DailyClosingAdmin(ReadOnlyAdmin):
    list_display = ("business_date", "bar", "status", "cash_expected_fcfa", "cash_counted_fcfa", "closed_by")
    list_filter = ("status", "bar")
    inlines = [ClosingLineInline]