from django.contrib import admin

from .models import Customer, Payment, Ticket, TicketLine, TicketSequence


class ReadOnlyAdmin(admin.ModelAdmin):
    """Les ventes ne se modifient jamais à la main : on corrige par une annulation ou un remboursement."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "bar", "phone", "credit_limit_fcfa", "is_active")
    list_filter = ("is_active", "bar")
    search_fields = ("name", "phone")


class LineInline(admin.TabularInline):
    model = TicketLine
    extra = 0
    can_delete = False
    fields = ("product_bar", "serving", "quantity", "unit_price_fcfa", "line_total_fcfa", "cogs_fcfa", "is_void", "void_reason")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    can_delete = False
    fields = ("kind", "amount_fcfa", "method", "paid_at", "received_by", "reference", "justification")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Ticket)
class TicketAdmin(ReadOnlyAdmin):
    list_display = ("label", "custom_name", "bar", "business_date", "status", "payment_status",
                    "total_fcfa", "amount_paid_fcfa", "customer")
    list_filter = ("status", "payment_status", "source", "bar")
    search_fields = ("label", "custom_name", "customer__name")
    date_hierarchy = "business_date"
    inlines = [LineInline, PaymentInline]


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    list_display = ("paid_at", "bar", "ticket", "kind", "amount_fcfa", "method", "received_by")
    list_filter = ("kind", "method", "bar")


@admin.register(TicketSequence)
class TicketSequenceAdmin(ReadOnlyAdmin):
    list_display = ("bar", "business_date", "counter")
    list_filter = ("bar",)