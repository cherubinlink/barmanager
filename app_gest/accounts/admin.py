from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import BarMembership, Role, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Profil", {"fields": ("phone", "avatar", "language")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Profil", {"fields": ("phone",)}),)
    list_display = ("username", "first_name", "last_name", "phone", "is_staff")
    search_fields = ("username", "first_name", "last_name", "phone", "email")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "bar", "is_system")
    list_filter = ("is_system",)
    search_fields = ("name", "bar__name")


@admin.register(BarMembership)
class BarMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "bar", "role", "is_owner", "is_active")
    list_filter = ("is_owner", "is_active")
    search_fields = ("user__username", "bar__name")