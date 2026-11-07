from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, F, Prefetch, Q
from django.utils import timezone

from accounts.models import BarMembership
from notifications.models import NotificationType
from notifications.services import mark_read as mark_notifications_read, notify

from . import realtime
from .customers import serialize_message
from .models import Conversation, ConversationParticipant, Message, UserPresence

Kind = Conversation.Kind
Role = ConversationParticipant.Role
DEFAULT_CHANNEL_NAME = "Équipe"


class ChatError(Exception):
    pass


# ------------------------------------------------------------------ membres et présence
def active_member_ids(bar):
    return set(BarMembership.objects.filter(bar=bar, is_active=True).values_list("user_id", flat=True))


def _fresh_since():
    return timezone.now() - timedelta(seconds=realtime.PRESENCE_TTL_SECONDS)


def members_with_presence(bar):
    """[(utilisateur, statut)] des membres actifs du bar, en ligne d'abord.
    « En ligne » = battement de cœur reçu dans les dernières 90 secondes (sinon hors ligne)."""
    ids = active_member_ids(bar)
    users = list(get_user_model().objects.filter(pk__in=ids))
    fresh = _fresh_since()
    status = {}
    for uid, st, seen in UserPresence.objects.filter(bar=bar, user_id__in=ids).values_list("user_id", "status", "last_seen_at"):
        online = st == UserPresence.Status.ONLINE and seen is not None and seen >= fresh
        status[uid] = UserPresence.Status.ONLINE if online else UserPresence.Status.OFFLINE
    rows = [(u, status.get(u.id, UserPresence.Status.OFFLINE)) for u in users]
    rows.sort(key=lambda r: (r[1] != UserPresence.Status.ONLINE, str(r[0]).lower()))
    return rows


def online_user_ids(bar):
    return list(UserPresence.objects.filter(bar=bar, status=UserPresence.Status.ONLINE,
                                            last_seen_at__gte=_fresh_since())
                .values_list("user_id", flat=True))


def reset_presence():
    """Facultatif : la présence expire déjà d'elle-même (90 s sans battement de cœur)."""
    return UserPresence.objects.exclude(status=UserPresence.Status.OFFLINE).update(
        status=UserPresence.Status.OFFLINE)


# ------------------------------------------------------------------ participants
def _join(conversation, user_id, role=Role.MEMBER):
    """Ajoute (ou réactive) un participant. Retourne True si la personne vient de rejoindre."""
    p, created = ConversationParticipant.objects.get_or_create(
        conversation=conversation, user_id=user_id, defaults={"role": role})
    if not created and p.left_at:
        p.left_at = None
        p.save(update_fields=["left_at", "updated_at"])
        return True
    return created


def ensure_default_channel(bar, user=None):
    """Canal « Équipe » du bar (créé au besoin). Si `user` est donné, il y est inscrit."""
    with transaction.atomic():
        conv = Conversation.objects.filter(bar=bar, is_default_channel=True).first()
        if conv is None:
            conv = Conversation.objects.create(bar=bar, kind=Kind.CHANNEL, name=DEFAULT_CHANNEL_NAME,
                                               is_default_channel=True)
        if user is not None and _join(conv, user.id):
            realtime.announce_joined(conv, [user.id])
    return conv


def sync_default_channel_members(bar):
    """Inscrit tous les membres actifs du bar au canal d'équipe (rattrapage). Retourne le nombre d'ajouts."""
    conv = ensure_default_channel(bar)
    added = [uid for uid in active_member_ids(bar) if _join(conv, uid)]
    realtime.announce_joined(conv, added)
    return len(added)


def start_direct(bar, user, other_id):
    if other_id == user.id:
        raise ChatError("Vous ne pouvez pas vous écrire à vous-même.")
    ids = active_member_ids(bar)
    if other_id not in ids or user.id not in ids:
        raise ChatError("Cette personne ne fait pas partie du bar.")
    other = get_user_model().objects.get(pk=other_id)
    conv = Conversation.get_or_create_direct(bar, user, other)
    if conv.is_archived:
        conv.is_archived = False
        conv.save(update_fields=["is_archived", "updated_at"])
    realtime.announce_joined(conv, [user.id, other.id])
    return conv


@transaction.atomic
def create_group(bar, creator, name, member_ids):
    name = (name or "").strip()
    if not name:
        raise ChatError("Donnez un nom au groupe.")
    wanted = set(member_ids) - {creator.id}
    if not wanted or not wanted <= active_member_ids(bar):
        raise ChatError("Choisissez au moins un membre du bar.")
    conv = Conversation.objects.create(bar=bar, kind=Kind.GROUP, name=name[:100], created_by=creator)
    _join(conv, creator.id, Role.ADMIN)
    for uid in wanted:
        _join(conv, uid)
    realtime.announce_joined(conv, wanted | {creator.id})
    post_system(conv, f"{creator} a créé le groupe « {conv.name} »")
    return conv


@transaction.atomic
def add_participants(conversation, actor, user_ids):
    if conversation.kind != Kind.GROUP:
        raise ChatError("On ne peut ajouter des personnes qu'à un groupe.")
    wanted = set(user_ids)
    if not wanted or not wanted <= active_member_ids(conversation.bar):
        raise ChatError("Choisissez des membres du bar.")
    added = [uid for uid in wanted if _join(conversation, uid)]
    if added:
        names = ", ".join(str(u) for u in get_user_model().objects.filter(pk__in=added))
        realtime.announce_joined(conversation, added)
        post_system(conversation, f"{actor} a ajouté {names}")
    return len(added)


@transaction.atomic
def remove_participant(conversation, actor, user_id):
    if conversation.kind != Kind.GROUP:
        raise ChatError("Action impossible sur cette conversation.")
    p = ConversationParticipant.objects.filter(conversation=conversation, user_id=user_id, left_at__isnull=True).first()
    if p is None or user_id == actor.id:
        raise ChatError("Participant introuvable.")
    p.left_at = timezone.now()
    p.save(update_fields=["left_at", "updated_at"])
    realtime.announce_left(conversation, [user_id])
    post_system(conversation, f"{actor} a retiré {p.user}")


@transaction.atomic
def leave_conversation(conversation, user):
    if conversation.kind != Kind.GROUP:
        raise ChatError("Vous ne pouvez quitter qu'un groupe.")
    p = ConversationParticipant.objects.select_for_update().get(conversation=conversation, user=user, left_at__isnull=True)
    p.left_at = timezone.now()
    p.save(update_fields=["left_at", "updated_at"])
    rest = conversation.participants.filter(left_at__isnull=True)
    if p.role == Role.ADMIN and rest.exists() and not rest.filter(role=Role.ADMIN).exists():
        successor = rest.order_by("created_at").first()          # le plus ancien devient administrateur
        successor.role = Role.ADMIN
        successor.save(update_fields=["role", "updated_at"])
    realtime.announce_left(conversation, [user.id])
    post_system(conversation, f"{user} a quitté le groupe")


def rename_group(conversation, name):
    if conversation.kind != Kind.GROUP:
        raise ChatError("Seul un groupe peut être renommé.")
    conversation.name = name.strip()[:100]
    conversation.save(update_fields=["name", "updated_at"])


def archive_conversation(conversation):
    if conversation.kind != Kind.GROUP:
        raise ChatError("Seul un groupe peut être archivé.")
    conversation.is_archived = True
    conversation.save(update_fields=["is_archived", "updated_at"])
    realtime.announce_left(conversation, list(conversation.participants.values_list("user_id", flat=True)))


# ------------------------------------------------------------------ messages
def message_payload(m):
    data = serialize_message(m)
    deleted = m.deleted_at is not None
    data.update({
        "body": "" if deleted else m.body, "deleted": deleted,
        "edited_at": m.edited_at.isoformat() if m.edited_at else None,
        "attachment_url": m.attachment.url if m.attachment and not deleted else "",
        "attachment_name": "" if deleted else m.attachment_name})
    return data


def _preview(body, attachment_name="", kind=Message.Kind.TEXT):
    if body:
        return body[:140]
    return {Message.Kind.IMAGE: "[Image]", Message.Kind.FILE: f"[Fichier] {attachment_name}"[:140],
            Message.Kind.TICKET_REF: "[Ticket partagé]", Message.Kind.PRODUCT_REF: "[Produit partagé]"}.get(kind, "")


def create_message(conversation, sender, *, body="", client_uuid=None, reply_to_id=None,
                   ticket_id=None, product_id=None, attachment=None):
    """Crée le message (idempotent grâce à client_uuid). Retourne (message, créé)."""
    body = (body or "").strip()
    if attachment:
        kind = Message.Kind.IMAGE if (getattr(attachment, "content_type", "") or "").startswith("image/") else Message.Kind.FILE
    elif ticket_id:
        kind = Message.Kind.TICKET_REF
    elif product_id:
        kind = Message.Kind.PRODUCT_REF
    else:
        kind = Message.Kind.TEXT
    if not (body or attachment or ticket_id or product_id):
        raise ChatError("Message vide.")
    if reply_to_id and not Message.objects.filter(pk=reply_to_id, conversation=conversation).exists():
        reply_to_id = None
    values = {"body": body, "kind": kind, "reply_to_id": reply_to_id, "related_ticket_id": ticket_id,
              "related_product_id": product_id, "attachment": attachment or None,
              "attachment_name": (attachment.name[:150] if attachment else "")}
    if client_uuid:
        msg, created = Message.objects.get_or_create(conversation=conversation, sender=sender,
                                                     client_uuid=client_uuid, defaults=values)
    else:
        msg, created = Message.objects.create(conversation=conversation, sender=sender, **values), True
    if created:
        Conversation.objects.filter(pk=conversation.pk).update(
            last_message_at=msg.created_at, last_message_preview=_preview(body, values["attachment_name"], kind))
    return msg, created


def notify_participants(conversation, sender, body):
    """Une seule notification non lue par conversation (dedup_key), comme dans le consommateur."""
    for p in (conversation.participants.select_related("user").exclude(user=sender)
              .filter(is_muted=False, left_at__isnull=True)):
        notify(recipient=p.user, bar=conversation.bar, type=NotificationType.CHAT_MESSAGE,
               title=conversation.name or str(sender), body=(body or "Pièce jointe")[:140],
               url=f"/chat/{conversation.id}/", dedup_key=f"chat:{conversation.id}",
               data={"conversation_id": conversation.id})


def send_message(conversation, sender, **kwargs):
    """Chemin HTTP (pièces jointes, repli sans WebSocket) : crée, diffuse en direct et notifie."""
    msg, created = create_message(conversation, sender, **kwargs)
    if created:
        realtime.broadcast_conversation(conversation.id, {"event": "message.new", "message": message_payload(msg)})
        notify_participants(conversation, sender, msg.body)
    return msg, created


def post_system(conversation, text):
    msg = Message.objects.create(conversation=conversation, sender=None, kind=Message.Kind.SYSTEM, body=text)
    Conversation.objects.filter(pk=conversation.pk).update(last_message_at=msg.created_at,
                                                           last_message_preview=text[:140])
    realtime.broadcast_conversation(conversation.id, {"event": "message.new", "message": message_payload(msg)})
    return msg


@transaction.atomic
def edit_message(message, user, body):
    message = Message.objects.select_for_update().select_related("sender").get(pk=message.pk)
    body = (body or "").strip()
    if message.sender_id != user.id or message.deleted_at or message.kind != Message.Kind.TEXT:
        raise ChatError("Ce message ne peut pas être modifié.")
    if not body:
        raise ChatError("Le message ne peut pas être vide.")
    message.body, message.edited_at = body, timezone.now()
    message.save(update_fields=["body", "edited_at", "updated_at"])
    realtime.broadcast_conversation(message.conversation_id, {"event": "message.edited", "message": message_payload(message)})
    return message


@transaction.atomic
def delete_message(message, user, can_moderate=False):
    """Suppression douce : le message reste dans la base, mais son contenu n'est plus montré."""
    message = Message.objects.select_for_update().get(pk=message.pk)
    if message.deleted_at:
        raise ChatError("Message déjà supprimé.")
    if message.sender_id != user.id and not can_moderate:
        raise ChatError("Vous ne pouvez supprimer que vos propres messages.")
    message.deleted_at, message.body = timezone.now(), ""
    message.save(update_fields=["deleted_at", "body", "updated_at"])
    last = (Message.objects.filter(conversation_id=message.conversation_id, deleted_at__isnull=True)
            .order_by("-id").first())
    Conversation.objects.filter(pk=message.conversation_id).update(
        last_message_preview=_preview(last.body, last.attachment_name, last.kind) if last else "")
    realtime.broadcast_conversation(message.conversation_id, {
        "event": "message.deleted", "conversation_id": message.conversation_id, "message_id": message.id})
    return message


def mark_conversation_read(conversation, user, message_id=None):
    now = timezone.now()
    if message_id is None:
        last = conversation.messages.order_by("-id").values_list("id", flat=True).first()
        message_id = last
    ConversationParticipant.objects.filter(conversation=conversation, user=user).update(
        last_read_at=now, last_read_message_id=message_id)
    mark_notifications_read(user, dedup_key=f"chat:{conversation.id}")
    realtime.broadcast_conversation(conversation.id, {
        "event": "read", "conversation_id": conversation.id, "user_id": user.id, "message_id": message_id})


# ------------------------------------------------------------------ lecture
def messages_before(conversation, before_id=None, limit=30):
    """Page d'historique (du plus ancien au plus récent) + indicateur « il y en a encore »."""
    qs = conversation.messages.select_related("sender").order_by("-id")
    if before_id:
        qs = qs.filter(id__lt=before_id)
    rows = list(qs[:limit + 1])
    return [message_payload(m) for m in reversed(rows[:limit])], len(rows) > limit


def search_messages(conversation, query, limit=30):
    qs = (conversation.messages.select_related("sender")
          .filter(deleted_at__isnull=True, body__icontains=query).order_by("-id")[:limit])
    return [message_payload(m) for m in qs]


def conversation_title(conversation, user):
    if conversation.kind == Kind.DIRECT:
        for p in conversation.participants.all():
            if p.user_id != user.id:
                return str(p.user)
        return "Conversation"
    return conversation.name or "Conversation"


def inbox(user, bar):
    """Conversations de l'utilisateur avec le nombre de messages non lus (une seule requête)."""
    unread = Count(
        "conversation__messages",
        filter=Q(conversation__messages__deleted_at__isnull=True) & ~Q(conversation__messages__sender_id=user.id)
        & (Q(last_read_at__isnull=True) | Q(conversation__messages__created_at__gt=F("last_read_at"))))
    parts = (ConversationParticipant.objects
             .filter(user=user, conversation__bar=bar, conversation__is_archived=False, left_at__isnull=True)
             .select_related("conversation")
             .prefetch_related(Prefetch("conversation__participants",
                                        queryset=ConversationParticipant.objects.filter(left_at__isnull=True).select_related("user")))
             .annotate(unread=unread)
             .order_by(F("conversation__last_message_at").desc(nulls_last=True), "-conversation_id"))
    return [{"participant": p, "conversation": p.conversation, "title": conversation_title(p.conversation, user),
             "unread": p.unread, "is_muted": p.is_muted} for p in parts]


def unread_summary(user, bar):
    rows = inbox(user, bar)
    return {"total": sum(r["unread"] for r in rows if not r["is_muted"]),
            "conversations": {r["conversation"].id: r["unread"] for r in rows}}


# ------------------------------------------------------------------ nettoyage
def purge_deleted_messages(days=30):
    """Supprime définitivement (base + fichiers) les messages supprimés depuis plus de `days` jours."""
    cutoff = timezone.now() - timedelta(days=days)
    qs = Message.objects.filter(deleted_at__lt=cutoff)
    for m in qs.exclude(attachment=""):
        m.attachment.delete(save=False)
    return qs.delete()[0]