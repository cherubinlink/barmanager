from django.contrib import admin, messages

from .models import Notification, NotificationPreference, PlatformAnnouncement, PushSubscription
from .services import publish_announcement


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "recipient", "bar", "type", "level", "title", "is_read", "occurrences")
    list_filter = ("type", "level", "is_read", "bar")
    search_fields = ("title", "body")
    date_hierarchy = "created_at"


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(ReadOnlyAdmin):
    list_display = ("user", "bar", "type", "in_app", "push", "sms", "email", "muted_until")
    list_filter = ("type", "bar")


@admin.register(PushSubscription)
class PushSubscriptionAdmin(ReadOnlyAdmin):
    """Les clés de chiffrement (p256dh, auth) et l'endpoint ne sont jamais affichés."""
    list_display = ("user", "user_agent", "is_active", "created_at")
    list_filter = ("is_active",)
    exclude = ("endpoint", "p256dh", "auth")


@admin.register(PlatformAnnouncement)
class PlatformAnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "level", "publish_at", "expires_at", "only_owners", "sent")
    list_filter = ("level", "sent", "only_owners")
    readonly_fields = ("sent",)
    actions = ["send_now"]

    @admin.action(description="Envoyer maintenant aux utilisateurs")
    def send_now(self, request, queryset):
        total = 0
        for announcement in queryset.filter(sent=False):
            total += publish_announcement(announcement)
        self.message_user(request, f"Annonce(s) envoyée(s) à {total} destinataire(s).", messages.SUCCESS)