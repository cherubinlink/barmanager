"""Diffusion temps réel depuis les vues HTTP vers les groupes du WebSocket (BarRealtimeConsumer).
Le format est celui attendu par le consommateur : {"type": "realtime.event", "payload": {...}}."""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

log = logging.getLogger(__name__)

# Une présence « en ligne » expire sans battement de cœur (ping client toutes les 30 s).
PRESENCE_TTL_SECONDS = 90


def _group_send(group, payload):
    try:
        layer = get_channel_layer()
        if layer is not None:
            async_to_sync(layer.group_send)(group, {"type": "realtime.event", "payload": payload})
    except Exception:                       # un souci de Redis ne doit jamais faire échouer la requête HTTP
        log.exception("Diffusion temps réel impossible (%s)", group)


def broadcast_conversation(conversation_id, payload):
    transaction.on_commit(lambda: _group_send(f"conv_{conversation_id}", payload))


def push_to_user(user_id, payload):
    transaction.on_commit(lambda: _group_send(f"user_{user_id}", payload))


def announce_joined(conversation, user_ids):
    """Fait rejoindre le groupe de la conversation aux WebSocket déjà ouverts de ces utilisateurs."""
    for uid in user_ids:
        push_to_user(uid, {"event": "conversation.joined", "conversation_id": conversation.id,
                           "kind": conversation.kind, "name": conversation.name})


def announce_left(conversation, user_ids):
    """Fait quitter le groupe : sans cela, un membre retiré continuerait de recevoir les messages."""
    for uid in user_ids:
        push_to_user(uid, {"event": "conversation.left", "conversation_id": conversation.id})