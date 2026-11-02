from django.db import models

# Create your models here.


from django.contrib.auth.models import AbstractUser
from django.db import models

from core.models import BarScopedModel

from accounts.permissions import DEFAULT_ROLES


class User(AbstractUser):
    """Utilisateur global : peut appartenir à plusieurs bars via BarMembership."""

    phone = models.CharField(max_length=20, blank=True, db_index=True)
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    language = models.CharField(max_length=5, default="fr")

    def __str__(self):
        return self.get_full_name() or self.username


class Role(BarScopedModel):
    """Rôle défini par bar (le gérant crée / modifie les siens)."""

    name = models.CharField(max_length=80)
    code = models.SlugField(max_length=40)
    permissions = models.JSONField(default=list, blank=True)
    is_system = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bar", "code"], name="uniq_role_code_per_bar")]
        ordering = ["name"]

    def __str__(self):
        return self.name

    def has_perm(self, perm: str) -> bool:
        return "*" in self.permissions or perm in self.permissions

    @classmethod
    def create_defaults(cls, bar):
        return {
            code: cls.objects.create(bar=bar, code=code, name=name, permissions=perms, is_system=True)
            for code, (name, perms) in DEFAULT_ROLES.items()
        }


class BarMembership(BarScopedModel):
    """Appartenance d'un utilisateur à un bar, avec son rôle."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")
    is_owner = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    invited_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bar", "user"], name="uniq_membership")]

    def __str__(self):
        return f"{self.user} @ {self.bar} ({self.role})"

    def has_perm(self, perm: str) -> bool:
        return self.is_active and (self.is_owner or self.role.has_perm(perm))
