import csv
from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import bar_required
from accounts.permissions import Perm
from catalog.models import ProductBar
from core.models import PeriodType
from inventory.services import stock_by_product

from .forms import ForecastFilterForm, RangeForm, RankingForm
from .models import DailySalesSummary, ProductDailyStat, Recommendation, SalesForecast
from .services import (build_range, compute_day, daily_series, expire_recommendations,
                       generate_forecasts, generate_recommendations, hourly_distribution,
                       latest_product_forecasts, pct_change, period_totals, product_ranking,
                       set_recommendation_status, weekday_averages)

REPORT = Perm.REPORT_VIEW
Status = Recommendation.Status


def _range(request, form_class=RangeForm):
    form = form_class(request.GET)
    form.is_valid()
    start, end = form.bounds(request.bar.current_business_date())
    return form, start, end


def _back(request, default):
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                  require_https=request.is_secure()):
        return redirect(target)
    return redirect(default)


# ================================================================== tableau de bord
@bar_required(REPORT)
def dashboard(request):
    bar = request.bar
    today = bar.current_business_date()
    form, start, end = _range(request)
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)

    totals, previous = period_totals(bar, start, end), period_totals(bar, prev_start, prev_end)
    series = daily_series(bar, start, end)
    ranking = product_ranking(bar, start, end)
    live, _ = compute_day(bar, today)                       # aujourd'hui en direct (les résumés sont nocturnes)
    hours_start = max(start, end - timedelta(days=89))
    top_recos = Recommendation.objects.filter(bar=bar, status__in=(Status.NEW, Status.SEEN)).select_related(
        "product_bar__product")[:4]
    return render(request, "analytics/dashboard.html", {
        "form": form, "start": start, "end": end, "totals": totals, "previous": previous,
        "changes": {k: pct_change(totals[k], previous[k]) for k in ("revenue", "margin", "tickets", "avg_ticket")},
        "series": series, "weekdays": weekday_averages(series), "hours": hourly_distribution(bar, hours_start, end),
        "top_products": ranking[:5], "slow_products": [r for r in reversed(ranking)][:5], "live": live, "today": today,
        "recommendations": top_recos,
        "new_recos": Recommendation.objects.filter(bar=bar, status=Status.NEW).count(),
        "forecast_days": SalesForecast.objects.filter(bar=bar, granularity=PeriodType.DAY, product_bar__isnull=True,
                                                      target_start__gt=today).order_by("target_start")[:7]})


@require_POST
@bar_required(REPORT, write=True)
def stats_refresh(request):
    """Recalcule les statistiques d'hier et d'aujourd'hui sans attendre la nuit."""
    today = request.bar.current_business_date()
    build_range(request.bar, today - timedelta(days=1), today)
    messages.success(request, "Statistiques recalculées.")
    return _back(request, "analytics:dashboard")


# ================================================================== journées
@bar_required(REPORT)
def summary_list(request):
    form, start, end = _range(request)
    qs = DailySalesSummary.objects.filter(bar=request.bar, business_date__range=(start, end))
    page = Paginator(qs, 31).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "analytics/summary_list.html", {
        "form": form, "start": start, "end": end, "page": page, "totals": period_totals(request.bar, start, end),
        "querystring": params.urlencode()})


@bar_required(REPORT)
def summary_detail(request, pk):
    summary = get_object_or_404(DailySalesSummary, pk=pk, bar=request.bar)
    stats = list(ProductDailyStat.objects.filter(bar=request.bar, business_date=summary.business_date)
                 .select_related("product_bar__product__category").order_by("-revenue_fcfa"))
    for s in stats:
        s.margin_fcfa = s.revenue_fcfa - s.cogs_fcfa
    return render(request, "analytics/summary_detail.html", {"summary": summary, "stats": stats})


@bar_required(REPORT)
def export_summaries(request):
    """Export CSV (séparateur « ; », ouvert directement par Excel en français)."""
    _, start, end = _range(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="ventes_{start:%Y%m%d}_{end:%Y%m%d}.csv"'
    response.write("\ufeff")
    w = csv.writer(response, delimiter=";")
    w.writerow(["Date", "Tickets", "Chiffre d'affaires", "Coût des marchandises", "Marge brute", "Pertes",
                "Encaissé", "Crédit accordé", "Heure de pointe"])
    for s in DailySalesSummary.objects.filter(bar=request.bar, business_date__range=(start, end)).order_by("business_date"):
        w.writerow([s.business_date.isoformat(), s.tickets_count, s.revenue_fcfa, s.cogs_fcfa, s.gross_margin_fcfa,
                    s.losses_fcfa, s.collected_fcfa, s.credit_granted_fcfa, "" if s.peak_hour is None else f"{s.peak_hour}h"])
    return response


# ================================================================== produits
@bar_required(REPORT)
def product_stats(request):
    form, start, end = _range(request, RankingForm)
    sort = form.cleaned_data.get("sort") or "revenue"
    rows = product_ranking(request.bar, start, end, sort, form.cleaned_data.get("q", "").strip())
    page = Paginator(rows, 40).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "analytics/product_stats.html", {
        "form": form, "start": start, "end": end, "sort": sort, "page": page, "querystring": params.urlencode(),
        "total_revenue": sum(r["revenue"] for r in rows), "total_margin": sum(r["margin"] for r in rows)})


@bar_required(REPORT)
def product_analysis(request, pk):
    pb = get_object_or_404(ProductBar.objects.select_related("product__category"), pk=pk, bar=request.bar)
    today = request.bar.current_business_date()
    daily = list(ProductDailyStat.objects.filter(bar=request.bar, product_bar=pb,
                                                 business_date__gte=today - timedelta(days=59)).order_by("business_date"))
    for d in daily:
        d.margin_fcfa = d.revenue_fcfa - d.cogs_fcfa
    forecast = latest_product_forecasts(request.bar).filter(product_bar=pb).first()
    s = stock_by_product(request.bar).get(pb.id, {"qty": 0, "value": 0})
    return render(request, "analytics/product_analysis.html", {
        "pb": pb, "daily": daily, "forecast": forecast, "stock": s["qty"], "stock_value": s["value"],
        "total_qty": sum(d.qty_sold for d in daily), "total_revenue": sum(d.revenue_fcfa for d in daily),
        "total_margin": sum(d.margin_fcfa for d in daily), "total_lost": sum(d.qty_lost for d in daily),
        "recommendations": Recommendation.objects.filter(bar=request.bar, product_bar=pb,
                                                         status__in=(Status.NEW, Status.SEEN))})


# ================================================================== prévisions
@bar_required(REPORT)
def forecast_list(request):
    bar = request.bar
    today = bar.current_business_date()
    form = ForecastFilterForm(request.GET)
    form.is_valid()
    qs = latest_product_forecasts(bar)
    q = form.cleaned_data.get("q", "").strip()
    if q:
        qs = qs.filter(Q(product_bar__product__name__icontains=q) | Q(product_bar__product__brand__icontains=q))
    within = form.cleaned_data.get("within")
    if within:
        qs = qs.filter(predicted_stockout_date__lte=today + timedelta(days=int(within)))
    qs = qs.order_by(F("predicted_stockout_date").asc(nulls_last=True), "-predicted_revenue_fcfa")
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    days = SalesForecast.objects.filter(bar=bar, granularity=PeriodType.DAY, product_bar__isnull=True,
                                        target_start__gt=today).order_by("target_start")[:7]
    week = SalesForecast.objects.filter(bar=bar, granularity=PeriodType.WEEK, product_bar__isnull=True,
                                        target_start__gt=today).first()
    return render(request, "analytics/forecast_list.html", {
        "form": form, "page": page, "today": today, "days": days, "week": week, "querystring": params.urlencode()})


@require_POST
@bar_required(REPORT, write=True)
def forecast_refresh(request):
    count = generate_forecasts(request.bar)
    if count:
        messages.success(request, "Prévisions recalculées.")
    else:
        messages.warning(request, "Pas assez d'historique : il faut au moins 14 jours de ventes enregistrées.")
    return _back(request, "analytics:forecast_list")


# ================================================================== recommandations
@bar_required(REPORT)
def recommendation_list(request):
    qs = Recommendation.objects.filter(bar=request.bar).select_related("product_bar__product")
    state = request.GET.get("state", "actives")
    if state == "actives":
        qs = qs.filter(status__in=(Status.NEW, Status.SEEN))
    elif state in Status.values:
        qs = qs.filter(status=state)
    else:
        state = "toutes"
    kind = request.GET.get("kind", "")
    if kind in Recommendation.Kind.values:
        qs = qs.filter(kind=kind)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "analytics/recommendation_list.html", {
        "page": page, "state": state, "kind": kind, "kinds": Recommendation.Kind.choices,
        "statuses": Status.choices, "querystring": params.urlencode(),
        "new_count": Recommendation.objects.filter(bar=request.bar, status=Status.NEW).count()})


@require_POST
@bar_required(REPORT, write=True)
def recommendation_status(request, pk):
    reco = get_object_or_404(Recommendation, pk=pk, bar=request.bar)
    try:
        set_recommendation_status(reco, request.POST.get("status", ""))
    except ValueError:
        messages.error(request, "Action invalide.")
    else:
        messages.success(request, {Status.SEEN: "Marquée comme vue.", Status.APPLIED: "Marquée comme appliquée.",
                                   Status.DISMISSED: "Recommandation ignorée."}[reco.status])
    return _back(request, "analytics:recommendation_list")


@require_POST
@bar_required(REPORT, write=True)
def recommendation_refresh(request):
    expire_recommendations(request.bar)
    created = generate_recommendations(request.bar)
    messages.success(request, f"{len(created)} nouvelle(s) recommandation(s)." if created
                     else "Aucune nouvelle recommandation pour le moment.")
    return _back(request, "analytics:recommendation_list")


# ================================================================== API JSON (graphiques)
@bar_required(REPORT)
def api_series(request):
    _, start, end = _range(request)
    return JsonResponse({"start": start.isoformat(), "end": end.isoformat(), "series": daily_series(request.bar, start, end)})


@bar_required(REPORT)
def api_hours(request):
    _, start, end = _range(request)
    return JsonResponse({"hours": hourly_distribution(request.bar, max(start, end - timedelta(days=89)), end)})


@bar_required(REPORT)
def api_top_products(request):
    _, start, end = _range(request)
    try:
        limit = min(max(int(request.GET.get("limit", 10)), 1), 50)
    except ValueError:
        limit = 10
    rows = product_ranking(request.bar, start, end, request.GET.get("sort", "revenue"))[:limit]
    return JsonResponse({"products": [{"id": r["product_bar_id"], "name": r["name"], "category": r["category"],
                                       "qty": float(r["qty"]), "revenue": r["revenue"], "margin": r["margin"],
                                       "margin_pct": r["margin_pct"]} for r in rows]})