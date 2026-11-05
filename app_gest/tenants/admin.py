from django.apps import apps
from django.contrib import admin, messages

from accounts.permissions import Perm

from .models import Bar, Plan, Subscription, SubscriptionPayment


def _notify_bar(payment, title):
    if not apps.is_installed("notifications"):
        return
    from notifications.models import Notification, NotificationType
    from notifications.services import notify_bar

    notify_bar(payment.subscription.bar, type=NotificationType.SUBSCRIPTION_PAYMENT, title=title,
               perm=Perm.SUBSCRIPTION_MANAGE, level=Notification.Level.INFO, url="/abonnement/")


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "price_fcfa", "duration_days", "max_users", "is_active", "sort_order")
    list_editable = ("price_fcfa", "is_active", "sort_order")
    prepopulated_fields = {"code": ("name",)}


@admin.register(Bar)
class BarAdmin(admin.ModelAdmin):
    list_display = ("name", "client_code", "owner", "city", "is_active", "created_at")
    list_filter = ("is_active", "city")
    search_fields = ("name", "client_code", "owner__username")
    readonly_fields = ("public_id",)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("bar", "plan", "status", "fin")
    list_filter = ("status", "plan")
    search_fields = ("bar__name",)
    actions = ["suspendre", "reactiver"]

    @admin.display(description="Fin")
    def fin(self, obj):
        return obj.ends_at

    @admin.action(description="Suspendre les abonnements sélectionnés")
    def suspendre(self, request, queryset):
        queryset.update(status=Subscription.Status.SUSPENDED)

    @admin.action(description="Réactiver (passe en « Actif » si la date de fin n'est pas dépassée)")
    def reactiver(self, request, queryset):
        for sub in queryset.filter(status=Subscription.Status.SUSPENDED):
            sub.status = Subscription.Status.ACTIVE if sub.current_period_end else Subscription.Status.TRIAL
            sub.save(update_fields=["status", "updated_at"])
            sub.refresh_status()


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = ("bar", "plan", "periods", "amount_fcfa", "method", "reference", "status", "created_at")
    list_filter = ("status", "method")
    search_fields = ("subscription__bar__name", "reference")
    readonly_fields = ("validated_by", "validated_at")
    actions = ["valider", "rejeter"]

    @admin.display(description="Bar")
    def bar(self, obj):
        return obj.subscription.bar

    @admin.action(description="✅ Valider les paiements sélectionnés")
    def valider(self, request, queryset):
        done = 0
        for payment in queryset.filter(status=SubscriptionPayment.Status.PENDING) \
                .select_related("subscription__bar", "plan"):
            payment.validate(request.user)
            _notify_bar(payment, "Paiement validé : votre abonnement est prolongé")
            done += 1
        self.message_user(request, f"{done} paiement(s) validé(s).", messages.SUCCESS)

    @admin.action(description="❌ Rejeter les paiements sélectionnés")
    def rejeter(self, request, queryset):
        done = 0
        for payment in queryset.filter(status=SubscriptionPayment.Status.PENDING) \
                .select_related("subscription__bar"):
            payment.reject(request.user, note="Paiement non retrouvé")
            _notify_bar(payment, "Paiement rejeté : vérifiez la référence et déclarez-le à nouveau")
            done += 1
        self.message_user(request, f"{done} paiement(s) rejeté(s).", messages.WARNING)