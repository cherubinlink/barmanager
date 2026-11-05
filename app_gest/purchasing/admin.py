from django.contrib import admin

from .models import PurchaseOrder, PurchaseOrderLine, Supplier, SupplierPayment


class LineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0
    readonly_fields = ("received_packages",)


class PaymentInline(admin.TabularInline):
    model = SupplierPayment
    extra = 0
    readonly_fields = ("paid_by",)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "bar", "phone", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "bar__name", "phone")


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("reference", "bar", "supplier", "status", "payment_status", "total_fcfa", "due_date")
    list_filter = ("status", "payment_status", "on_credit")
    search_fields = ("reference", "supplier__name", "bar__name")
    inlines = [LineInline, PaymentInline]