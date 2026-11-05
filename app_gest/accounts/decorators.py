from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .permissions import Perm
from .utils import active_memberships, resolve_membership

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _read_only(bar):
    subscription = getattr(bar, "subscription", None)
    if subscription is None:
        return False
    subscription.refresh_status()
    return subscription.is_read_only


def bar_required(perm=None, write=False):
    """Exige un utilisateur connecté, rattaché à un bar (et, au besoin, une permission).
    `perm` peut être une permission ou un tuple de permissions (il suffit d'en avoir UNE).
    `write=True` : bloque les envois de formulaire (POST…) quand l'abonnement est expiré.
    Place `request.bar` et `request.membership` à disposition de la vue."""
    perms = (perm,) if isinstance(perm, str) else tuple(perm or ())

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            membership = resolve_membership(request)
            if membership is None:
                if active_memberships(request.user).exists():
                    return redirect("accounts:select_bar")
                return redirect("accounts:no_bar")
            if perms and not any(membership.has_perm(p) for p in perms):
                raise PermissionDenied
            if write and request.method not in SAFE_METHODS and _read_only(membership.bar):
                messages.error(request, "Abonnement expiré : votre bar est en lecture seule. "
                                        "Réglez votre abonnement pour continuer.")
                target = ("tenants:subscription"
                          if membership.has_perm(Perm.SUBSCRIPTION_MANAGE) else "dashboard:home")
                return redirect(target)
            request.membership = membership
            request.bar = membership.bar
            return view(request, *args, **kwargs)

        return wrapper

    return decorator