import io

import qrcode
from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.decorators import bar_required
from accounts.permissions import Perm
from tenants.client_identity import get_client_identity, set_client_name

from .forms import BarSettingsForm, EnterCodeForm, PaymentDeclareForm
from .models import Bar, Plan, Subscription, SubscriptionPayment
from tenants.plans import annotate_plans



# ------------------------------------------------------------------ réglages du bar
@bar_required(Perm.BAR_SETTINGS, write=True)
def bar_settings(request):
    form = BarSettingsForm(request.POST or None, instance=request.bar)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Réglages enregistrés.")
        return redirect("tenants:settings")
    return render(request, "tenants/settings.html", {"form": form})


# ------------------------------------------------------------------ QR code
def _public_url(request, bar):
    base = getattr(settings, "SITE_BASE_URL", "").rstrip("/") or request.build_absolute_uri("/").rstrip("/")
    return base + reverse("tenants:public_entry", args=[bar.public_id])


@bar_required()
def bar_qr(request):
    return render(request, "tenants/qr.html", {"public_url": _public_url(request, request.bar)})


@bar_required()
def bar_qr_png(request):
    image = qrcode.make(_public_url(request, request.bar), box_size=10, border=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return HttpResponse(buffer.getvalue(), content_type="image/png")


# ------------------------------------------------------------------ pages publiques (client)
def enter_code(request):
    """Le client saisit le code du bar (alternative au scan du QR code)."""
    form = EnterCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        return redirect("tenants:public_entry", public_id=form.bar.public_id)
    return render(request, "accounts/auth_form.html", {
        "form": form, "title": "Entrer le code du bar",
        "subtitle": "Le code est affiché dans le bar, à côté du QR code. Pas besoin de compte.",
        "submit": "Continuer", "alt_url": "accounts:login",
        "alt_text": "Je fais partie du personnel du bar"})


def public_entry(request, public_id):
    """Page d'arrivée du QR code (ou du code saisi) : le client reçoit un nom automatique
    (ClientA1…), puis voit le menu et les prix du bar."""
    bar = get_object_or_404(Bar, public_id=public_id, is_active=True)
    identity = get_client_identity(request, bar)
    if request.method == "POST" and identity:
        set_client_name(request, bar, request.POST.get("name", ""))
        return redirect("tenants:public_entry", public_id=bar.public_id)

    from catalog.models import ProductBar

    products = (ProductBar.objects.filter(bar=bar, is_active=True)
                .select_related("product__category").order_by("product__category__name", "product__name"))
    menu = {}
    for pb in products:
        menu.setdefault(pb.product.category.name, []).append(pb)
    return render(request, "tenants/public_bar.html",
                  {"public_bar": bar, "menu": menu, "identity": identity})


# ------------------------------------------------------------------ abonnement
def _notify_platform_admins(payment):
    if not apps.is_installed("notifications"):
        return
    from accounts.models import User
    from notifications.models import Notification, NotificationType
    from notifications.services import notify

    bar = payment.subscription.bar
    for admin_user in User.objects.filter(is_superuser=True, is_active=True):
        notify(recipient=admin_user, type=NotificationType.SUBSCRIPTION_PAYMENT,
               title=f"Paiement à valider : {bar.name}",
               body=f"{payment.amount_fcfa} FCFA via {payment.get_method_display()} (réf. {payment.reference})",
               level=Notification.Level.WARNING, url="/admin/tenants/subscriptionpayment/")



@bar_required(Perm.SUBSCRIPTION_MANAGE)
def subscription(request):
    sub = get_object_or_404(Subscription, bar=request.bar)
    sub.refresh_status()
    has_pending = sub.payments.filter(status=SubscriptionPayment.Status.PENDING).exists()
    form = PaymentDeclareForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if has_pending:
            messages.error(request, "Un paiement est déjà en attente de validation.")
            return redirect("tenants:subscription")
        if form.is_valid():
            payment = form.save(sub, request.user)
            _notify_platform_admins(payment)
            messages.success(request, "Paiement déclaré. Il sera validé par l'administrateur sous peu.")
            return redirect("tenants:subscription")
    return render(request, "tenants/subscription.html", {
        "sub": sub, "form": form, "has_pending": has_pending,
         "plans": annotate_plans(Plan.objects.filter(is_active=True).order_by("price_fcfa")),
        "payments": sub.payments.select_related("plan")[:10],
        "instructions": getattr(settings, "PAYMENT_INSTRUCTIONS",
                                "Contactez l'administrateur pour connaître les numéros de paiement."),
    })