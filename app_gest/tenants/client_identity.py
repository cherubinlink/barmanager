"""Identité anonyme d'un client qui arrive par QR code ou en saisissant le code du bar."""
import uuid

SESSION_KEY = "client_identity"


def _ordering_open(bar):
    if not bar.qr_ordering_enabled:
        return False
    subscription = getattr(bar, "subscription", None)
    if subscription is None:
        return True
    subscription.refresh_status()
    return not subscription.is_read_only


def get_client_identity(request, bar):
    """Nom automatique du client (ClientA1, ClientA2…) pour la journée d'activité du bar.

    Mémorisé en session : le client garde le même nom s'il recharge la page.
    Retourne None si le bar n'accepte pas (ou plus) les commandes par QR."""
    if not _ordering_open(bar):
        return None
    day = bar.current_business_date().isoformat()
    identities = request.session.get(SESSION_KEY, {})
    entry = identities.get(str(bar.public_id))
    if entry and entry["day"] == day:
        return entry
    from sales.models import TicketSequence

    _, label = TicketSequence.next_label(bar)
    entry = {"label": label, "day": day, "name": "", "token": uuid.uuid4().hex}
    identities[str(bar.public_id)] = entry
    request.session[SESSION_KEY] = identities
    return entry


def set_client_name(request, bar, name):
    """Le client peut remplacer ClientA3 par son prénom (facultatif)."""
    identities = request.session.get(SESSION_KEY, {})
    entry = identities.get(str(bar.public_id))
    if entry:
        entry["name"] = name.strip()[:40]
        request.session[SESSION_KEY] = identities