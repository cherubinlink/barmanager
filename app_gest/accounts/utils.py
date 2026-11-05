from accounts.models import BarMembership

SESSION_KEY = "current_bar_id"


def active_memberships(user):
    return (BarMembership.objects
            .filter(user=user, is_active=True, bar__is_active=True)
            .select_related("bar", "role"))


def resolve_membership(request):
    """Bar courant : celui choisi en session, sinon l'unique bar de l'utilisateur."""
    qs = active_memberships(request.user)
    bar_id = request.session.get(SESSION_KEY)
    if bar_id:
        membership = qs.filter(bar_id=bar_id).first()
        if membership:
            return membership
    memberships = list(qs[:2])
    if len(memberships) == 1:
        request.session[SESSION_KEY] = memberships[0].bar_id
        return memberships[0]
    return None


def owns_a_bar(user):
    """Seul le propriétaire d'un bar peut en créer un autre."""
    return user.is_authenticated and user.owned_bars.exists()