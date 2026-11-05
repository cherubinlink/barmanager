from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import DecimalField, F, ProtectedError, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import bar_required
from accounts.permissions import Perm

from catalog.forms import PackagingForm, ProductBarForm, ProposeProductForm, ServingForm
from catalog.models import (Category, PackagingUnit, ProductBar, ServingOption,
                     normalize_name)
from catalog.services import record_price, visible_global_products


def _form_page(request, form, title, back_url, submit="Enregistrer", subtitle=""):
    return render(request, "catalog/form.html", {
        "form": form, "title": title, "back_url": back_url, "submit": submit, "subtitle": subtitle})


def _warn_if_loss(request, product_bar):
    if product_bar.purchase_price_fcfa and product_bar.sale_price_fcfa < product_bar.purchase_price_fcfa:
        messages.warning(request, "Attention : le prix de vente est inférieur au prix d'achat "
                                  "(vous vendez à perte).")


# ------------------------------------------------------------------ liste
@bar_required()
def product_list(request):
    bar, membership = request.bar, request.membership
    qs = (ProductBar.objects.filter(bar=bar).select_related("product__category")
          .annotate(stock=Coalesce(
              Sum("lots__remaining_qty", filter=Q(lots__status="OPEN")), Value(Decimal("0")),
              output_field=DecimalField(max_digits=14, decimal_places=3))))
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(product__name__icontains=q) | Q(product__brand__icontains=q))
    category = request.GET.get("category", "")
    if category.isdigit():
        qs = qs.filter(product__category_id=int(category))
    state = request.GET.get("state", "actifs")
    if state == "actifs":
        qs = qs.filter(is_active=True)
    elif state == "inactifs":
        qs = qs.filter(is_active=False)
    elif state == "bas":
        qs = qs.filter(is_active=True, stock__lte=F("low_stock_threshold"))
    page = Paginator(qs.order_by("product__category__name", "product__name"), 30).get_page(
        request.GET.get("page"))
    items = list(page.object_list)
    page.object_list = items
    for pb in items:                       # calculé en Python (évite un souci de soustraction d'entiers non signés en MySQL)
        pb.margin = pb.sale_price_fcfa - pb.purchase_price_fcfa
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "catalog/product_list.html", {
        "page": page, "q": q, "state": state, "category": category,
        "categories": Category.objects.filter(products__bar_products__bar=bar).distinct().order_by("name"),
        "querystring": params.urlencode(),
        "can_costs": membership.has_perm(Perm.PRICE_EDIT),
        "can_stock": membership.has_perm(Perm.STOCK_VIEW),
        "can_add": membership.has_perm(Perm.CATALOG_ADD),
    })


# ------------------------------------------------------------------ ajout d'un produit
@bar_required(Perm.CATALOG_ADD)
def product_add(request):
    """Étape 1 : rechercher le produit dans le catalogue commun."""
    q = request.GET.get("q", "").strip()
    results = []
    if q:
        norm = normalize_name(q)
        match = Q(name__icontains=q) | Q(brand__icontains=q)
        if norm:
            match |= Q(normalized_name__contains=norm)
        results = list(visible_global_products(request.bar).filter(match)
                       .exclude(bar_products__bar=request.bar)
                       .select_related("category").order_by("name", "volume_cl")[:30])
    return render(request, "catalog/product_add.html", {"q": q, "results": results})


@bar_required(Perm.CATALOG_ADD, write=True)
def product_add_existing(request, pk):
    """Étape 2 : fixer ses prix pour un produit du catalogue commun."""
    product = get_object_or_404(visible_global_products(request.bar), pk=pk)
    existing = ProductBar.objects.filter(bar=request.bar, product=product).first()
    if existing:
        messages.info(request, "Ce produit est déjà dans votre catalogue.")
        return redirect("catalog:product_detail", pk=existing.pk)
    form = ProductBarForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            pb = form.save(commit=False)
            pb.bar, pb.product = request.bar, product
            pb.save()
            record_price(pb, request.user)
        messages.success(request, f"« {product} » ajouté à votre catalogue.")
        _warn_if_loss(request, pb)
        return redirect("catalog:product_detail", pk=pb.pk)
    return _form_page(request, form, f"Ajouter : {product}", "catalog:product_add",
                      submit="Ajouter à mon catalogue",
                      subtitle="Vos prix restent privés : chaque bar fixe les siens.")


@bar_required(Perm.CATALOG_ADD, write=True)
def product_propose(request):
    """Produit absent du catalogue : le bar le crée ; il rejoint le catalogue commun après validation."""
    form = ProposeProductForm(request.POST or None, bar=request.bar)
    if request.method == "POST" and form.is_valid():
        pb = form.save()
        record_price(pb, request.user)
        messages.success(request, f"« {pb.product} » ajouté. Il sera proposé aux autres bars "
                                  "après validation par la plateforme.")
        _warn_if_loss(request, pb)
        return redirect("catalog:product_detail", pk=pb.pk)
    return _form_page(request, form, "Nouveau produit", "catalog:product_add", submit="Créer le produit",
                      subtitle="Vérifiez d'abord avec la recherche que le produit n'existe pas déjà.")


# ------------------------------------------------------------------ fiche produit
@bar_required()
def product_detail(request, pk):
    pb = get_object_or_404(ProductBar.objects.select_related("product__category"), pk=pk, bar=request.bar)
    m = request.membership
    can_costs, can_stock = m.has_perm(Perm.PRICE_EDIT), m.has_perm(Perm.STOCK_VIEW)
    margin = None
    if can_costs and pb.sale_price_fcfa:
        amount = pb.sale_price_fcfa - pb.purchase_price_fcfa
        margin = {"amount": amount, "percent": round(amount * 100 / pb.sale_price_fcfa)}
    return render(request, "catalog/product_detail.html", {
        "pb": pb, "margin": margin,
        "stock": pb.current_stock() if can_stock else None,
        "lots": list(pb.lots.filter(status="OPEN")[:10]) if can_stock else [],
        "packagings": pb.packagings.all(), "servings": pb.servings.all(),
        "history": list(pb.price_history.all()[:10]) if can_costs else [],
        "can_costs": can_costs, "can_stock": can_stock,
        "can_price": can_costs, "can_pack": m.has_perm(Perm.PURCHASE_MANAGE),
    })


@bar_required(Perm.PRICE_EDIT, write=True)
def product_edit(request, pk):
    pb = get_object_or_404(ProductBar.objects.select_related("product"), pk=pk, bar=request.bar)
    form = ProductBarForm(request.POST or None, instance=pb, show_active=True)
    if request.method == "POST" and form.is_valid():
        price_changed = {"sale_price_fcfa", "purchase_price_fcfa"} & set(form.changed_data)
        with transaction.atomic():
            pb = form.save()
            if price_changed:
                record_price(pb, request.user)
        messages.success(request, "Produit mis à jour.")
        if price_changed:
            _warn_if_loss(request, pb)
        return redirect("catalog:product_detail", pk=pb.pk)
    return _form_page(request, form, f"Prix : {pb.product}", "catalog:product_list")


@require_POST
@bar_required(Perm.PRICE_EDIT, write=True)
def product_toggle(request, pk):
    """Un produit ne se supprime pas (il a un historique de ventes) : on le désactive."""
    pb = get_object_or_404(ProductBar, pk=pk, bar=request.bar)
    pb.is_active = not pb.is_active
    pb.save(update_fields=["is_active", "updated_at"])
    messages.success(request, "Produit réactivé." if pb.is_active else "Produit désactivé : il n'est plus proposé à la vente.")
    return redirect("catalog:product_detail", pk=pb.pk)


# ------------------------------------------------------------------ conditionnements (casier, carton…)
@bar_required(Perm.PURCHASE_MANAGE, write=True)
def packaging_add(request, pk):
    pb = get_object_or_404(ProductBar.objects.select_related("product"), pk=pk, bar=request.bar)
    form = PackagingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        packaging = form.save(commit=False)
        packaging.bar, packaging.product_bar = request.bar, pb
        packaging.save()
        _single_default(packaging)
        messages.success(request, "Conditionnement ajouté.")
        return redirect("catalog:product_detail", pk=pb.pk)
    return render(request, "catalog/form.html", {
        "form": form, "title": f"Conditionnement : {pb.product}", "submit": "Ajouter",
        "back_url": "catalog:product_detail", "back_args": [pb.pk]})


@bar_required(Perm.PURCHASE_MANAGE, write=True)
def packaging_edit(request, pk):
    packaging = get_object_or_404(PackagingUnit.objects.select_related("product_bar__product"),
                                  pk=pk, bar=request.bar)
    form = PackagingForm(request.POST or None, instance=packaging)
    if request.method == "POST" and form.is_valid():
        packaging = form.save()
        _single_default(packaging)
        messages.success(request, "Conditionnement mis à jour.")
        return redirect("catalog:product_detail", pk=packaging.product_bar_id)
    return render(request, "catalog/form.html", {
        "form": form, "title": f"Modifier : {packaging.name}", "submit": "Enregistrer",
        "back_url": "catalog:product_detail", "back_args": [packaging.product_bar_id]})


@require_POST
@bar_required(Perm.PURCHASE_MANAGE, write=True)
def packaging_delete(request, pk):
    packaging = get_object_or_404(PackagingUnit, pk=pk, bar=request.bar)
    product_pk = packaging.product_bar_id
    packaging.delete()
    messages.success(request, "Conditionnement supprimé.")
    return redirect("catalog:product_detail", pk=product_pk)


def _single_default(packaging):
    if packaging.is_default_purchase:
        (PackagingUnit.objects.filter(product_bar=packaging.product_bar)
         .exclude(pk=packaging.pk).update(is_default_purchase=False))


# ------------------------------------------------------------------ portions (verre, mesure…)
@bar_required(Perm.PRICE_EDIT, write=True)
def serving_add(request, pk):
    pb = get_object_or_404(ProductBar.objects.select_related("product"), pk=pk, bar=request.bar)
    form = ServingForm(request.POST or None, initial={"is_active": True})
    if request.method == "POST" and form.is_valid():
        serving = form.save(commit=False)
        serving.bar, serving.product_bar = request.bar, pb
        serving.save()
        messages.success(request, "Portion ajoutée.")
        return redirect("catalog:product_detail", pk=pb.pk)
    return render(request, "catalog/form.html", {
        "form": form, "title": f"Portion : {pb.product}", "submit": "Ajouter",
        "subtitle": "Pour vendre au verre ou à la mesure (vin, whisky).",
        "back_url": "catalog:product_detail", "back_args": [pb.pk]})


@bar_required(Perm.PRICE_EDIT, write=True)
def serving_edit(request, pk):
    serving = get_object_or_404(ServingOption.objects.select_related("product_bar__product"),
                                pk=pk, bar=request.bar)
    form = ServingForm(request.POST or None, instance=serving)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Portion mise à jour.")
        return redirect("catalog:product_detail", pk=serving.product_bar_id)
    return render(request, "catalog/form.html", {
        "form": form, "title": f"Modifier : {serving.name}", "submit": "Enregistrer",
        "back_url": "catalog:product_detail", "back_args": [serving.product_bar_id]})


@require_POST
@bar_required(Perm.PRICE_EDIT, write=True)
def serving_delete(request, pk):
    serving = get_object_or_404(ServingOption, pk=pk, bar=request.bar)
    product_pk = serving.product_bar_id
    try:
        serving.delete()
        messages.success(request, "Portion supprimée.")
    except ProtectedError:
        serving.is_active = False
        serving.save(update_fields=["is_active", "updated_at"])
        messages.info(request, "Cette portion a déjà été vendue : elle est désactivée au lieu d'être supprimée.")
    return redirect("catalog:product_detail", pk=product_pk)


# ------------------------------------------------------------------ recherche JSON (caisse)
@bar_required()
def api_products(request):
    """Produits vendables du bar : alimente la recherche de la caisse."""
    q = request.GET.get("q", "").strip()
    qs = (ProductBar.objects.filter(bar=request.bar, is_active=True)
          .select_related("product").prefetch_related("servings").order_by("product__name"))
    if q:
        qs = qs.filter(Q(product__name__icontains=q) | Q(product__brand__icontains=q))
    return JsonResponse({"results": [{
        "id": pb.id, "name": str(pb.product), "price": pb.sale_price_fcfa,
        "servings": [{"id": s.id, "name": s.name, "price": s.price_fcfa, "base_units": str(s.base_units)}
                     for s in pb.servings.all() if s.is_active],
    } for pb in qs[:20]]})