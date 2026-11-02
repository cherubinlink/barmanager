from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from tenants.models import TRIAL_DAYS
from tenants.services import create_bar

from accounts.forms import BarForm, RegisterForm
from accounts.utils import SESSION_KEY, active_memberships


def _create_bar(user, form):
    return create_bar(
        owner=user,
        name=form.cleaned_data["bar_name"],
        client_code=form.cleaned_data["client_code"],
        city=form.cleaned_data["city"],
    )


def _welcome(request, bar):
    request.session[SESSION_KEY] = bar.id
    messages.success(
        request, f"Bienvenue ! Votre essai gratuit de {TRIAL_DAYS} jours commence aujourd'hui.")
    return redirect("dashboard:home")


def register(request):
    """Inscription : crée l'utilisateur ET son bar (rôles, essai de 30 jours, canal d'équipe)."""
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            bar = _create_bar(user, form)
        login(request, user)
        return _welcome(request, bar)
    return render(request, "accounts/auth_form.html", {
        "form": form, "title": "Créer mon compte",
        "subtitle": f"{TRIAL_DAYS} jours d'essai gratuit, sans engagement.",
        "submit": "Créer mon compte", "alt_url": "accounts:login",
        "alt_text": "J'ai déjà un compte"})


@login_required
def new_bar(request):
    """Un utilisateur existant crée un (autre) bar dont il devient le gérant."""
    form = BarForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            bar = _create_bar(request.user, form)
        return _welcome(request, bar)
    return render(request, "accounts/auth_form.html", {
        "form": form, "title": "Créer un bar", "submit": "Créer le bar"})


@login_required
def select_bar(request):
    """Choix du bar quand l'utilisateur appartient à plusieurs bars."""
    memberships = list(active_memberships(request.user))
    if request.method == "POST":
        bar_id = request.POST.get("bar_id")
        if any(str(m.bar_id) == bar_id for m in memberships):
            request.session[SESSION_KEY] = int(bar_id)
            return redirect("dashboard:home")
        messages.error(request, "Bar introuvable.")
    return render(request, "accounts/select_bar.html", {"memberships": memberships})


@login_required
def no_bar(request):
    if active_memberships(request.user).exists():
        return redirect("dashboard:home")
    return render(request, "accounts/no_bar.html")