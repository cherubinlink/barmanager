import json

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import bar_required
from accounts.permissions import Perm

from .forms import (AddParticipantsForm, DirectForm, EditMessageForm, GroupForm, MessageForm,
                    RenameForm)
from .models import Conversation, ConversationParticipant, Message
from .services import (ChatError, add_participants, archive_conversation, conversation_title,
                       create_group, delete_message, edit_message, inbox, leave_conversation,
                       mark_conversation_read, members_with_presence, messages_before, online_user_ids,
                       remove_participant, rename_group, search_messages, send_message, start_direct,
                       sync_default_channel_members, ensure_default_channel, unread_summary)

Kind = Conversation.Kind
Role = ConversationParticipant.Role
CHAT = Perm.CHAT_USE


def _form_page(request, form, title, back_url, back_args=None, submit="Enregistrer", subtitle=""):
    return render(request, "chat/form.html", {
        "form": form, "title": title, "back_url": back_url, "back_args": back_args or [],
        "submit": submit, "subtitle": subtitle})


def _participant(request, pk):
    """La personne doit être participante active de cette conversation du bar courant."""
    return get_object_or_404(
        ConversationParticipant.objects.select_related("conversation"),
        conversation_id=pk, conversation__bar=request.bar, user=request.user, left_at__isnull=True)


def _can_manage(request, participant):
    return participant.conversation.kind == Kind.GROUP and (
        participant.role == Role.ADMIN or request.membership.is_owner)


def _can_post(request, conversation):
    """Le canal d'équipe est réservé aux personnes autorisées à écrire à toute l'équipe."""
    return conversation.kind != Kind.CHANNEL or request.membership.has_perm(Perm.CHAT_BROADCAST)


def _data(request):
    """Corps de requête JSON ou formulaire classique."""
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
    return request.POST


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


# ================================================================== pages
@bar_required(CHAT)
def conversation_list(request):
    ensure_default_channel(request.bar, request.user)
    rows = inbox(request.user, request.bar)
    return render(request, "chat/list.html", {
        "rows": rows, "unread_total": sum(r["unread"] for r in rows if not r["is_muted"]),
        "ws_path": f"/ws/bar/{request.bar.id}/"})


@bar_required(CHAT)
def conversation_detail(request, pk):
    participant = _participant(request, pk)
    conv = participant.conversation
    history, has_more = messages_before(conv, limit=50)
    mark_conversation_read(conv, request.user)
    people = [p for p in conv.participants.filter(left_at__isnull=True).select_related("user")]
    return render(request, "chat/detail.html", {
        "conversation": conv, "participant": participant, "title": conversation_title(conv, request.user),
        "history": history, "has_more": has_more, "people": people,
        "can_post": _can_post(request, conv), "can_manage": _can_manage(request, participant),
        "can_leave": conv.kind == Kind.GROUP, "online_ids": online_user_ids(request.bar),
        "rows": inbox(request.user, request.bar), "ws_path": f"/ws/bar/{request.bar.id}/"})


@bar_required(CHAT)
def member_list(request):
    """Annuaire de l'équipe avec présence : point de départ d'une discussion privée."""
    rows = [(u, s) for u, s in members_with_presence(request.bar) if u.id != request.user.id]
    return render(request, "chat/members.html", {"rows": rows})


@require_POST
@bar_required(CHAT, write=True)
def direct_start(request):
    form = DirectForm(request.POST)
    if form.is_valid():
        try:
            conv = start_direct(request.bar, request.user, form.cleaned_data["user_id"])
        except ChatError as exc:
            messages.error(request, str(exc))
        else:
            return redirect("chat:conversation_detail", pk=conv.pk)
    return redirect("chat:member_list")


@bar_required(CHAT, write=True)
def group_create(request):
    form = GroupForm(request.POST or None, bar=request.bar, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            conv = create_group(request.bar, request.user, form.cleaned_data["name"],
                                [u.id for u in form.cleaned_data["members"]])
        except ChatError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Groupe créé.")
            return redirect("chat:conversation_detail", pk=conv.pk)
    return _form_page(request, form, "Nouveau groupe", "chat:conversation_list", submit="Créer le groupe",
                      subtitle="Seuls les membres de votre bar peuvent être ajoutés.")


@bar_required(CHAT, write=True)
def group_rename(request, pk):
    participant = _participant(request, pk)
    if not _can_manage(request, participant):
        messages.error(request, "Seul un administrateur du groupe peut le renommer.")
        return redirect("chat:conversation_detail", pk=pk)
    form = RenameForm(request.POST or None, initial={"name": participant.conversation.name})
    if request.method == "POST" and form.is_valid():
        rename_group(participant.conversation, form.cleaned_data["name"])
        messages.success(request, "Groupe renommé.")
        return redirect("chat:conversation_detail", pk=pk)
    return _form_page(request, form, "Renommer le groupe", "chat:conversation_detail", [pk])


@bar_required(CHAT, write=True)
def participants_add(request, pk):
    participant = _participant(request, pk)
    if not _can_manage(request, participant):
        messages.error(request, "Seul un administrateur du groupe peut ajouter des personnes.")
        return redirect("chat:conversation_detail", pk=pk)
    form = AddParticipantsForm(request.POST or None, bar=request.bar, conversation=participant.conversation)
    if request.method == "POST" and form.is_valid():
        try:
            add_participants(participant.conversation, request.user, [u.id for u in form.cleaned_data["members"]])
        except ChatError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Participants ajoutés.")
            return redirect("chat:conversation_detail", pk=pk)
    return _form_page(request, form, "Ajouter des participants", "chat:conversation_detail", [pk], submit="Ajouter")


@require_POST
@bar_required(CHAT, write=True)
def participant_remove(request, pk, user_id):
    participant = _participant(request, pk)
    if not _can_manage(request, participant):
        messages.error(request, "Seul un administrateur du groupe peut retirer une personne.")
    else:
        try:
            remove_participant(participant.conversation, request.user, user_id)
            messages.success(request, "Participant retiré.")
        except ChatError as exc:
            messages.error(request, str(exc))
    return redirect("chat:conversation_detail", pk=pk)


@require_POST
@bar_required(CHAT, write=True)
def conversation_leave(request, pk):
    participant = _participant(request, pk)
    try:
        leave_conversation(participant.conversation, request.user)
    except ChatError as exc:
        messages.error(request, str(exc))
        return redirect("chat:conversation_detail", pk=pk)
    messages.info(request, "Vous avez quitté le groupe.")
    return redirect("chat:conversation_list")


@require_POST
@bar_required(CHAT)
def conversation_mute(request, pk):
    participant = _participant(request, pk)
    participant.is_muted = not participant.is_muted
    participant.save(update_fields=["is_muted", "updated_at"])
    messages.info(request, "Conversation en sourdine." if participant.is_muted else "Notifications réactivées.")
    return redirect("chat:conversation_detail", pk=pk)


@require_POST
@bar_required(CHAT, write=True)
def conversation_archive(request, pk):
    participant = _participant(request, pk)
    if not _can_manage(request, participant):
        messages.error(request, "Seul un administrateur du groupe peut l'archiver.")
        return redirect("chat:conversation_detail", pk=pk)
    archive_conversation(participant.conversation)
    messages.success(request, "Groupe archivé.")
    return redirect("chat:conversation_list")


# ================================================================== API JSON (le temps réel passe par le WebSocket)
@bar_required(CHAT)
def api_messages(request, pk):
    """Historique paginé : ?before=<id du plus ancien message affiché>&limit=30."""
    conv = _participant(request, pk).conversation
    try:
        limit = min(max(int(request.GET.get("limit", 30)), 1), 100)
        before = int(request.GET["before"]) if request.GET.get("before") else None
    except ValueError:
        return _error("Paramètres invalides.")
    items, has_more = messages_before(conv, before, limit)
    return JsonResponse({"messages": items, "has_more": has_more})


@require_POST
@bar_required(CHAT, write=True)
def api_send(request, pk):
    """Envoi par HTTP : pièces jointes (impossibles par WebSocket) ou repli quand le WebSocket est coupé.
    Le message est diffusé instantanément aux autres participants."""
    conv = _participant(request, pk).conversation
    if not _can_post(request, conv):
        return _error("Seules les personnes autorisées peuvent écrire dans ce canal.", 403)
    form = MessageForm(_data(request), request.FILES, bar=request.bar)
    if not form.is_valid():
        return JsonResponse({"error": "Message invalide.", "fields": form.errors}, status=400)
    d = form.cleaned_data
    try:
        msg, created = send_message(conv, request.user, body=d["body"], client_uuid=d["client_uuid"],
                                    reply_to_id=d["reply_to_id"], ticket_id=d["ticket_id"],
                                    product_id=d["product_id"], attachment=d["attachment"])
    except ChatError as exc:
        return _error(str(exc))
    from .services import message_payload
    return JsonResponse({"message": message_payload(msg), "created": created}, status=201 if created else 200)


def _message_for_user(request, msg_pk):
    msg = get_object_or_404(Message.objects.select_related("conversation", "sender"), pk=msg_pk,
                            conversation__bar=request.bar)
    participant = get_object_or_404(ConversationParticipant, conversation=msg.conversation, user=request.user,
                                    left_at__isnull=True)
    return msg, participant


@require_POST
@bar_required(CHAT, write=True)
def api_edit(request, msg_pk):
    msg, _ = _message_for_user(request, msg_pk)
    form = EditMessageForm(_data(request))
    if not form.is_valid():
        return _error("Message invalide.")
    try:
        edit_message(msg, request.user, form.cleaned_data["body"])
    except ChatError as exc:
        return _error(str(exc), 403)
    return JsonResponse({"ok": True})


@require_POST
@bar_required(CHAT, write=True)
def api_delete(request, msg_pk):
    msg, participant = _message_for_user(request, msg_pk)
    can_moderate = participant.role == Role.ADMIN or request.membership.is_owner
    try:
        delete_message(msg, request.user, can_moderate)
    except ChatError as exc:
        return _error(str(exc), 403)
    return JsonResponse({"ok": True})


@require_POST
@bar_required(CHAT)
def api_read(request, pk):
    conv = _participant(request, pk).conversation
    raw = _data(request).get("message_id")
    mark_conversation_read(conv, request.user, int(raw) if str(raw).isdigit() else None)
    return JsonResponse({"ok": True, "unread": unread_summary(request.user, request.bar)["total"]})


@bar_required(CHAT)
def api_unread(request):
    """Pastille de la messagerie : total et nombre par conversation."""
    return JsonResponse(unread_summary(request.user, request.bar))


@bar_required(CHAT)
def api_presence(request):
    return JsonResponse({"online": online_user_ids(request.bar)})


@bar_required(CHAT)
def api_search(request, pk):
    conv = _participant(request, pk).conversation
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"messages": []})
    return JsonResponse({"messages": search_messages(conv, q)})