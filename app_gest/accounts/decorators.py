from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .utils import active_memberships, resolve_membership


def bar_required(perm=None):
    """Exige un utilisateur connecté, rattaché à un bar (et, au besoin, une permission).
    Place `request.bar` et `request.membership` à disposition de la vue."""

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            membership = resolve_membership(request)
            if membership is None:
                if active_memberships(request.user).exists():
                    return redirect("accounts:select_bar")
                return redirect("accounts:no_bar")
            if perm and not membership.has_perm(perm):
                raise PermissionDenied
            request.membership = membership
            request.bar = membership.bar
            return view(request, *args, **kwargs)

        return wrapper

    return decorator