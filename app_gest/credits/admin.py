from django.contrib import admin

from .models import CustomerCredit, CustomerCreditPayment, PaymentReminder


class ReadOnlyAdmin(admin.ModelAdmin):
    """Les créances ne se modifient jamais à la main : on corrige par un règlement ou une perte."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class _ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class PaymentInline(_ReadOnlyInline):
    model = CustomerCreditPayment
    fields = ("paid_at", "amount_fcfa", "method", "received_by", "reference")


class ReminderInline(_ReadOnlyInline):
    model = PaymentReminder
    fk_name = "customer_credit"
    fields = ("created_at", "channel", "sent_by", "message")


@admin.register(CustomerCredit)
class CustomerCreditAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "bar", "customer", "amount_fcfa", "amount_paid_fcfa", "due_date", "status")
    list_filter = ("status", "bar")
    search_fields = ("customer__name", "customer__phone")
    inlines = [PaymentInline, ReminderInline]


@admin.register(CustomerCreditPayment)
class CustomerCreditPaymentAdmin(ReadOnlyAdmin):
    list_display = ("paid_at", "bar", "credit", "amount_fcfa", "method", "received_by")
    list_filter = ("method", "bar")


@admin.register(PaymentReminder)
class PaymentReminderAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "bar", "customer_credit", "channel", "sent_by")
    list_filter = ("channel", "bar")