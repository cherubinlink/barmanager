import json

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import bar_required

from .forms import CHANNELS, MuteForm, PreferencesForm
from .models import Notification, NotificationPreference, NotificationType, PushSubscription
from .services import mark_read, mute_all, notify, serialize, unread_count, visible


def _back(request, default="notifications:list"):
    """Retour sûr vers la page d'origine (champ « next »), sinon vers la liste."""
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                  require_https=request.is_secure()):
        return redirect(target)
    return redirect(default)


def _json_body(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# ================================================================== centre de notifications
@bar_required()
def notification_list(request):
    qs = visible(request.user, request.bar)
    state = request.GET.get("state", "")
    if state == "non_lues":
        qs = qs.filter(is_read=False)
    ntype = request.GET.get("type", "")
    if ntype in NotificationType.values:
        qs = qs.filter(type=ntype)
    level = request.GET.get("level", "")
    if level in Notification.Level.values:
        qs = qs.filter(level=level)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "notifications/list.html", {
        "page": page, "state": state, "type": ntype, "level": level,
        "types": NotificationType.choices, "levels": Notification.Level.choices,
        "unread": unread_count(request.user, request.bar), "querystring": params.urlencode()})


@bar_required()
def notification_open(request, pk):
    """Marque la notification comme lue puis ouvre son lien interne."""
    notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
    mark_read(request.user, ids=[notif.pk])
    if notif.url and url_has_allowed_host_and_scheme(notif.url, allowed_hosts={request.get_host()},
                                                     require_https=request.is_secure()):
        return redirect(notif.url)
    return redirect("notifications:list")


@require_POST
@bar_required()
def notification_read(request, pk):
    notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
    mark_read(request.user, ids=[notif.pk])
    return _back(request)


@require_POST
@bar_required()
def mark_all_read(request):
    ids = list(visible(request.user, request.bar).filter(is_read=False).values_list("id", flat=True))
    mark_read(request.user, ids=ids)
    messages.success(request, "Toutes les notifications sont marquées comme lues.")
    return _back(request)


@require_POST
@bar_required()
def notification_delete(request, pk):
    get_object_or_404(Notification, pk=pk, recipient=request.user).delete()
    return _back(request)


@require_POST
@bar_required()
def clear_read(request):
    deleted = visible(request.user, request.bar).filter(is_read=True).delete()[0]
    messages.success(request, f"{deleted} notification(s) lue(s) supprimée(s).")
    return _back(request)


# ================================================================== API (cloche en temps réel)
@bar_required()
def api_summary(request):
    """Compteur + dernières notifications, pour la cloche et le rechargement après reconnexion WebSocket."""
    try:
        limit = min(max(int(request.GET.get("limit", 10)), 1), 30)
    except ValueError:
        limit = 10
    items = visible(request.user, request.bar)[:limit]
    return JsonResponse({"unread": unread_count(request.user, request.bar),
                         "items": [serialize(n) for n in items]})


@require_POST
@bar_required()
def api_mark_read(request):
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Requête invalide."}, status=400)
    if payload.get("all"):
        ids = list(visible(request.user, request.bar).filter(is_read=False).values_list("id", flat=True))
    else:
        raw = payload.get("ids")
        ids = [int(i) for i in raw if str(i).isdigit()] if isinstance(raw, list) else []
    updated = mark_read(request.user, ids=ids)
    return JsonResponse({"updated": updated, "unread": unread_count(request.user, request.bar)})


# ================================================================== préférences
@bar_required()
def preferences(request):
    form = PreferencesForm(request.POST or None, user=request.user, bar=request.bar)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Préférences de notification enregistrées.")
        return redirect("notifications:preferences")
    muted = (NotificationPreference.objects
             .filter(user=request.user, bar=request.bar, muted_until__gt=timezone.now())
             .order_by("-muted_until").values_list("muted_until", flat=True).first())
    return render(request, "notifications/preferences.html", {
        "form": form, "rows": form.rows(), "channels": CHANNELS, "mute_form": MuteForm(),
        "muted_until": muted,
        "push_devices": PushSubscription.objects.filter(user=request.user, is_active=True).count()})


@require_POST
@bar_required()
def mute(request):
    form = MuteForm(request.POST)
    if form.is_valid():
        hours = int(form.cleaned_data["hours"])
        until = mute_all(request.user, request.bar, hours or None)
        messages.success(request, f"Notifications en sourdine jusqu'à {timezone.localtime(until):%d/%m %H:%M}."
                         if until else "Notifications réactivées.")
    return redirect("notifications:preferences")


@require_POST
@bar_required()
def send_test(request):
    """Envoie une notification de test à soi-même pour vérifier le temps réel."""
    n = notify(recipient=request.user, bar=request.bar, type=NotificationType.SYSTEM,
               title="Notification de test", body="Si vous la voyez, tout fonctionne.",
               url="/notifications/")
    messages.success(request, "Notification de test envoyée." if n
                     else "Le type « Annonce plateforme » est désactivé dans vos préférences.")
    return redirect("notifications:preferences")


# ================================================================== Web Push (PWA)
@bar_required()
def push_config(request):
    return JsonResponse({"publicKey": getattr(settings, "VAPID_PUBLIC_KEY", "")})


@require_POST
@bar_required()
def push_subscribe(request):
    payload = _json_body(request)
    keys = (payload or {}).get("keys") or {}
    endpoint, p256dh, auth = (payload or {}).get("endpoint"), keys.get("p256dh"), keys.get("auth")
    if not (endpoint and p256dh and auth):
        return JsonResponse({"error": "Abonnement invalide."}, status=400)
    PushSubscription.objects.update_or_create(
        endpoint=endpoint, defaults={"user": request.user, "p256dh": p256dh, "auth": auth, "is_active": True,
                                     "user_agent": request.META.get("HTTP_USER_AGENT", "")[:255]})
    return JsonResponse({"ok": True})


@require_POST
@bar_required()
def push_unsubscribe(request):
    payload = _json_body(request) or {}
    PushSubscription.objects.filter(user=request.user, endpoint=payload.get("endpoint", "")).delete()
    return JsonResponse({"ok": True})