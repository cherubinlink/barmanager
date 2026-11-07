from django.contrib import admin

from .models import Conversation, ConversationParticipant, Message, UserPresence


class ReadOnlyAdmin(admin.ModelAdmin):
    """La messagerie ne se modifie pas à la main : l'admin sert à superviser."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ParticipantInline(admin.TabularInline):
    model = ConversationParticipant
    extra = 0
    can_delete = False
    fields = ("user", "role", "is_muted", "last_read_at", "left_at")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Conversation)
class ConversationAdmin(ReadOnlyAdmin):
    list_display = ("id", "bar", "kind", "name", "is_default_channel", "is_archived", "last_message_at")
    list_filter = ("kind", "is_archived", "bar")
    search_fields = ("name",)
    inlines = [ParticipantInline]


@admin.register(Message)
class MessageAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "conversation", "sender", "kind", "short_body", "deleted_at")
    list_filter = ("kind", "conversation__bar")
    date_hierarchy = "created_at"

    @admin.display(description="Contenu")
    def short_body(self, obj):
        return "(supprimé)" if obj.deleted_at else obj.body[:60]


@admin.register(UserPresence)
class UserPresenceAdmin(ReadOnlyAdmin):
    list_display = ("user", "bar", "status", "last_seen_at")
    list_filter = ("status", "bar")