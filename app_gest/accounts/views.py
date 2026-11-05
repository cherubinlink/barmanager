from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.shortcuts import redirect, render,get_object_or_404
from django.views.decorators.http import require_POST

from tenants.models import TRIAL_DAYS

from tenants.models import TRIAL_DAYS
from tenants.services import create_bar

from accounts.decorators import bar_required
from accounts.forms import (BarForm, MemberAddForm, MemberEditForm, ProfileForm,RegisterForm, RoleForm)
from accounts.utils import SESSION_KEY, active_memberships,owns_a_bar
from accounts.models import BarMembership, Role
from accounts.permissions import Perm
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
    return redirect("dashboard:homes")


def register(request):
    """Inscription : crée l'utilisateur ET son bar (rôles, essai de 30 jours, canal d'équipe)."""
    if request.user.is_authenticated:
        return redirect("dashboard:homes")
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
    """Un propriétaire de bar en crée un (autre) dont il devient le gérant."""
    if not owns_a_bar(request.user):
        messages.error(request, "Seul le propriétaire d'un bar peut en créer un autre.")
        return redirect("dashboard:homes")
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
            return redirect("dashboard:homes")
        messages.error(request, "Bar introuvable.")
    return render(request, "accounts/select_bar.html", {"memberships": memberships})


@login_required
def no_bar(request):
    if active_memberships(request.user).exists():
        return redirect("dashboard:homes")
    return render(request, "accounts/no_bar.html")

class StaffLoginView(LoginView):
    """Page de connexion : personnel du bar (identifiant + mot de passe) ET entrée client (code du bar).
    Utilise le même gabarit que l'inscription : accounts/auth_form.html."""

    template_name = "accounts/auth_form.html"
    redirect_authenticated_user = True
    extra_context = {
        "title": "Connexion",
        "subtitle": "Personnel du bar : gérant, caissier, vendeuse, magasinier.",
        "submit": "Se connecter",
        "alt_url": "accounts:register",
        "alt_text": "Créer un compte",
    }

    def get_context_data(self, **kwargs):
        from tenants.forms import EnterCodeForm

        context = super().get_context_data(**kwargs)
        context["client_form"] = EnterCodeForm()
        return context


# ------------------------------------------------------------------ équipe
def _members_info(bar):
    subscription = getattr(bar, "subscription", None)
    limit = subscription.plan.max_users if subscription and subscription.plan else None
    active = BarMembership.objects.filter(bar=bar, is_active=True).count()
    return limit, active


@bar_required(Perm.USER_MANAGE)
def team(request):
    members = (BarMembership.objects.filter(bar=request.bar).select_related("user", "role")
               .order_by("-is_owner", "-is_active", "user__first_name"))
    limit, active = _members_info(request.bar)
    return render(request, "accounts/team.html", {
        "members": members, "limit": limit, "active_count": active})


@bar_required(Perm.USER_MANAGE, write=True)
def member_add(request):
    limit, active = _members_info(request.bar)
    if limit and active >= limit:
        messages.error(request, f"Votre abonnement est limité à {limit} utilisateurs actifs.")
        return redirect("accounts:team")
    form = MemberAddForm(request.POST or None, bar=request.bar)
    if request.method == "POST" and form.is_valid():
        membership = form.save(invited_by=request.user)
        messages.success(request, f"{membership.user} a été ajouté(e) à l'équipe.")
        return redirect("accounts:team")
    return render(request, "accounts/auth_form.html", {
        "form": form, "title": "Ajouter un membre", "submit": "Créer le compte",
        "alt_url": "accounts:team", "alt_text": "Retour à l'équipe"})


@bar_required(Perm.USER_MANAGE, write=True)
def member_edit(request, pk):
    membership = get_object_or_404(BarMembership.objects.select_related("user", "role"),
                                   pk=pk, bar=request.bar)
    if membership.is_owner:
        messages.info(request, "Le propriétaire du bar ne peut pas être modifié.")
        return redirect("accounts:team")
    if membership.user_id == request.user.id:
        messages.info(request, "Vous ne pouvez pas modifier votre propre rôle ici.")
        return redirect("accounts:team")
    # Mot de passe réinitialisable seulement si la personne n'appartient qu'à CE bar
    # (sinon un gérant pourrait prendre le contrôle d'un compte utilisé ailleurs).
    can_reset = not BarMembership.objects.filter(user=membership.user).exclude(bar=request.bar).exists()
    form = MemberEditForm(request.POST or None, membership=membership, can_reset_password=can_reset)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Modifications enregistrées.")
        return redirect("accounts:team")
    return render(request, "accounts/auth_form.html", {
        "form": form, "title": f"Modifier {membership.user}", "submit": "Enregistrer",
        "alt_url": "accounts:team", "alt_text": "Retour à l'équipe"})


# ------------------------------------------------------------------ rôles
@bar_required(Perm.USER_MANAGE)
def roles(request):
    from django.db.models import Count
    roles_qs = Role.objects.filter(bar=request.bar).annotate(n=Count("memberships")).order_by("name")
    return render(request, "accounts/roles.html", {"roles": roles_qs})


@bar_required(Perm.USER_MANAGE, write=True)
def role_add(request):
    form = RoleForm(request.POST or None, bar=request.bar)
    if request.method == "POST" and form.is_valid():
        role = form.save()
        messages.success(request, f"Rôle « {role.name} » créé.")
        return redirect("accounts:roles")
    return render(request, "accounts/auth_form.html", {
        "form": form, "title": "Nouveau rôle", "submit": "Créer le rôle",
        "alt_url": "accounts:roles", "alt_text": "Retour aux rôles"})


@bar_required(Perm.USER_MANAGE, write=True)
def role_edit(request, pk):
    role = get_object_or_404(Role, pk=pk, bar=request.bar)
    if role.code == "gerant" and role.is_system:
        messages.info(request, "Le rôle Gérant a tous les droits et ne peut pas être modifié.")
        return redirect("accounts:roles")
    form = RoleForm(request.POST or None, bar=request.bar, instance=role)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Rôle mis à jour.")
        return redirect("accounts:roles")
    return render(request, "accounts/auth_form.html", {
        "form": form, "title": f"Rôle : {role.name}", "submit": "Enregistrer",
        "alt_url": "accounts:roles", "alt_text": "Retour aux rôles"})


@require_POST
@bar_required(Perm.USER_MANAGE, write=True)
def role_delete(request, pk):
    role = get_object_or_404(Role, pk=pk, bar=request.bar)
    if role.is_system:
        messages.error(request, "Les rôles par défaut ne peuvent pas être supprimés.")
    elif role.memberships.exists():
        messages.error(request, "Ce rôle est attribué à des membres : changez leur rôle d'abord.")
    else:
        role.delete()
        messages.success(request, "Rôle supprimé.")
    return redirect("accounts:roles")


# ------------------------------------------------------------------ profil
@login_required
def profile(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profil mis à jour.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})