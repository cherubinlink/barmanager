"""Envoi d'événements temps réel (Django Channels) depuis n'importe quelle app."""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def _send(group: str, event: str, payload: dict):
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(
        group, {"type": "realtime.event", "payload": {"event": event, **payload}}
    )


def send_to_bar(bar_id, event, payload=None):
    """Diffuse à tous les utilisateurs connectés d'un bar (ex: ticket mis à jour)."""
    _send(f"bar_{bar_id}", event, payload or {})


def send_to_user(user_id, event, payload=None):
    """Diffuse à un utilisateur (toutes ses connexions : notifications, etc.)."""
    _send(f"user_{user_id}", event, payload or {})


def send_to_conversation(conversation_id, event, payload=None):
    _send(f"conv_{conversation_id}", event, payload or {})
