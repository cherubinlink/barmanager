"""Un seul WebSocket par utilisateur et par bar. Il transporte :
   - les messages de chat (groupes conv_<id>)
   - les notifications personnelles (groupe user_<id>)
   - les événements du bar : tickets, stock, présence (groupe bar_<id>)
"""
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from accounts.models import BarMembership
from notifications.models import NotificationType
from notifications.services import mark_read, notify

from .models import Conversation, ConversationParticipant, Message, UserPresence


def serialize_message(m: Message) -> dict:
    return {
        "id": m.id, "conversation_id": m.conversation_id, "sender_id": m.sender_id,
        "sender_name": str(m.sender) if m.sender else "",
        "kind": m.kind, "body": m.body, "client_uuid": str(m.client_uuid),
        "reply_to_id": m.reply_to_id, "ticket_id": m.related_ticket_id,
        "product_id": m.related_product_id, "created_at": m.created_at.isoformat(),
    }


class BarRealtimeConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        self.bar_id = int(self.scope["url_route"]["kwargs"]["bar_id"])
        if not self.user.is_authenticated or not await self.is_member():
            await self.close(code=4403)
            return
        self.joined = {f"bar_{self.bar_id}", f"user_{self.user.id}"}
        self.joined |= {f"conv_{cid}" for cid in await self.conversation_ids()}
        for group in self.joined:
            await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()
        await self.set_presence(UserPresence.Status.ONLINE)
        await self.broadcast_presence("ONLINE")

    async def disconnect(self, code):
        if not hasattr(self, "joined"):
            return
        for group in self.joined:
            await self.channel_layer.group_discard(group, self.channel_name)
        await self.set_presence(UserPresence.Status.OFFLINE)
        await self.broadcast_presence("OFFLINE")

    # ---------- messages entrants (client -> serveur) ----------
    async def receive_json(self, content, **kwargs):
        action = content.get("action")
        if action == "message.send":
            msg = await self.save_message(content)
            if msg is None:
                await self.send_json({"event": "error", "detail": "Conversation inaccessible."})
                return
            await self.channel_layer.group_send(
                f"conv_{msg['conversation_id']}",
                {"type": "realtime.event", "payload": {"event": "message.new", "message": msg}},
            )
            await self.notify_participants(msg)
        elif action == "typing":
            await self.channel_layer.group_send(
                f"conv_{content['conversation_id']}",
                {"type": "realtime.event", "payload": {
                    "event": "typing", "conversation_id": content["conversation_id"],
                    "user_id": self.user.id, "is_typing": bool(content.get("is_typing", True))}},
            )
        elif action == "read":
            await self.mark_conversation_read(content["conversation_id"], content.get("message_id"))
            await self.channel_layer.group_send(
                f"conv_{content['conversation_id']}",
                {"type": "realtime.event", "payload": {
                    "event": "read", "conversation_id": content["conversation_id"],
                    "user_id": self.user.id, "message_id": content.get("message_id")}},
            )
        elif action == "ping":
            await self.send_json({"event": "pong"})

    # ---------- événements sortants (serveur -> client) ----------
    async def realtime_event(self, event):
        payload = event["payload"]
        if payload.get("event") == "conversation.joined":  # nouvelle conversation créée par un collègue
            group = f"conv_{payload['conversation_id']}"
            await self.channel_layer.group_add(group, self.channel_name)
            self.joined.add(group)
        await self.send_json(payload)

    async def broadcast_presence(self, status):
        await self.channel_layer.group_send(
            f"bar_{self.bar_id}",
            {"type": "realtime.event", "payload": {"event": "presence", "user_id": self.user.id, "status": status}},
        )

    # ---------- accès base de données ----------
    @database_sync_to_async
    def is_member(self):
        return BarMembership.objects.filter(bar_id=self.bar_id, user=self.user, is_active=True).exists()

    @database_sync_to_async
    def conversation_ids(self):
        return list(ConversationParticipant.objects.filter(
            user=self.user, conversation__bar_id=self.bar_id, left_at__isnull=True
        ).values_list("conversation_id", flat=True))

    @database_sync_to_async
    def set_presence(self, status):
        UserPresence.objects.update_or_create(
            bar_id=self.bar_id, user=self.user,
            defaults={"status": status, "last_seen_at": timezone.now()},
        )

    @database_sync_to_async
    def save_message(self, content):
        conv_id = content.get("conversation_id")
        if not ConversationParticipant.objects.filter(
            conversation_id=conv_id, conversation__bar_id=self.bar_id,
            user=self.user, left_at__isnull=True,
        ).exists():
            return None
        body = (content.get("body") or "").strip()
        if not body and not content.get("ticket_id") and not content.get("product_id"):
            return None
        msg, created = Message.objects.get_or_create(  # idempotent : renvoi réseau sans doublon
            conversation_id=conv_id, sender=self.user, client_uuid=content["client_uuid"],
            defaults={
                "body": body, "reply_to_id": content.get("reply_to_id"),
                "kind": Message.Kind.TICKET_REF if content.get("ticket_id") else
                        Message.Kind.PRODUCT_REF if content.get("product_id") else Message.Kind.TEXT,
                "related_ticket_id": content.get("ticket_id"),
                "related_product_id": content.get("product_id"),
            },
        )
        if created:
            Conversation.objects.filter(pk=conv_id).update(
                last_message_at=msg.created_at, last_message_preview=body[:140])
        return serialize_message(msg)

    @database_sync_to_async
    def notify_participants(self, msg):
        """Une seule notification non lue par conversation (dedup_key), qui se met à jour."""
        conv = Conversation.objects.get(pk=msg["conversation_id"])
        for p in conv.participants.select_related("user").exclude(user=self.user).filter(
                is_muted=False, left_at__isnull=True):
            notify(
                recipient=p.user, bar=conv.bar, type=NotificationType.CHAT_MESSAGE,
                title=conv.name or str(self.user), body=msg["body"][:140],
                url=f"/chat/{conv.id}/", dedup_key=f"chat:{conv.id}",
                data={"conversation_id": conv.id},
            )

    @database_sync_to_async
    def mark_conversation_read(self, conversation_id, message_id):
        now = timezone.now()
        ConversationParticipant.objects.filter(conversation_id=conversation_id, user=self.user).update(
            last_read_at=now, last_read_message_id=message_id)
        mark_read(self.user, dedup_key=f"chat:{conversation_id}")
