import math
import statistics
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.db.models import BigIntegerField, Case, Count, DecimalField, ExpressionWrapper, F, Max, Q, Sum, When
from django.utils import timezone

from catalog.models import ProductBar
from core.models import PeriodType
from inventory.models import StockMovement
from inventory.services import LOSS_KINDS, date_to_datetime, stock_by_product
from sales.models import Payment, Ticket, TicketLine

from .models import DailySalesSummary, ProductDailyStat, Recommendation, SalesForecast

ZERO = Decimal("0")
METHOD = "moving_average_weekday"
HISTORY_DAYS = 56            # fenêtre d'apprentissage des prévisions (8 semaines)
MIN_HISTORY_DAYS = 14        # en dessous : pas assez d'historique pour prévoir
EXCLUDED = (Ticket.Status.CANCELLED, Ticket.Status.PENDING_VALIDATION)
SIGNED = Case(When(kind=Payment.Kind.REFUND, then=-F("amount_fcfa")), default=F("amount_fcfa"),
              output_field=BigIntegerField())
WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def _int(value):
    return int(Decimal(value or 0).quantize(Decimal("1")))


def pct_change(current, previous):
    """Variation en % (None si la période précédente est vide)."""
    return None if not previous else round((current - previous) * 100 / previous, 1)


def _lines(bar, start, end):
    return (TicketLine.objects.filter(ticket__bar=bar, ticket__business_date__range=(start, end), is_void=False)
            .exclude(ticket__status__in=EXCLUDED))


def _tickets(bar, start, end):
    return Ticket.objects.filter(bar=bar, business_date__range=(start, end)).exclude(status__in=EXCLUDED)


def _loss_movements(bar, start, end):
    return StockMovement.objects.filter(bar=bar, business_date__range=(start, end), kind__in=LOSS_KINDS)


# ------------------------------------------------------------------ calcul d'une journée
def _loss_value(bar, day):
    value = ExpressionWrapper(F("quantity") * F("unit_cost_fcfa"),
                              output_field=DecimalField(max_digits=18, decimal_places=2))
    total = _loss_movements(bar, day, day).aggregate(v=Sum(value))["v"]
    return _int(-total) if total else 0


def _collected(bar, day):
    """Encaissé du jour : paiements des tickets (nets des remboursements) + règlements de créances reçus ce jour-là."""
    total = Payment.objects.filter(bar=bar, ticket__business_date=day).aggregate(t=Sum(SIGNED))["t"] or 0
    if apps.is_installed("credits"):
        from credits.models import CustomerCreditPayment
        start = date_to_datetime(day)                       # bornes calculées en Python (pas de fonction SQL de fuseau)
        total += (CustomerCreditPayment.objects.filter(bar=bar, paid_at__gte=start, paid_at__lt=start + timedelta(days=1))
                  .aggregate(t=Sum("amount_fcfa"))["t"] or 0)
    return int(total)


def _credit_granted(bar, day):
    if not apps.is_installed("credits"):
        return 0
    from credits.models import CustomerCredit
    return int(CustomerCredit.objects.filter(bar=bar, ticket__business_date=day).aggregate(t=Sum("amount_fcfa"))["t"] or 0)


def _peak_hour(lines):
    by_hour = defaultdict(int)
    for added_at, total in lines.values_list("added_at", "line_total_fcfa"):
        by_hour[timezone.localtime(added_at).hour] += total
    return max(by_hour, key=by_hour.get) if by_hour else None


def compute_day(bar, day):
    """Chiffres d'une journée, sans rien enregistrer : (résumé, {id_produit_bar: stats})."""
    lines = _lines(bar, day, day)
    t = _tickets(bar, day, day).filter(total_fcfa__gt=0).aggregate(n=Count("id"), revenue=Sum("total_fcfa"))
    revenue, cogs = int(t["revenue"] or 0), _int(lines.aggregate(c=Sum("cogs_fcfa"))["c"])
    summary = {"tickets_count": t["n"] or 0, "revenue_fcfa": revenue, "cogs_fcfa": cogs,
               "gross_margin_fcfa": revenue - cogs, "losses_fcfa": _loss_value(bar, day),
               "collected_fcfa": _collected(bar, day), "credit_granted_fcfa": _credit_granted(bar, day),
               "peak_hour": _peak_hour(lines)}

    products = {r["product_bar_id"]: {"qty_sold": r["q"] or ZERO, "revenue_fcfa": int(r["r"] or 0),
                                      "cogs_fcfa": _int(r["c"]), "qty_lost": ZERO}
                for r in lines.values("product_bar_id")
                .annotate(q=Sum("base_quantity"), r=Sum("line_total_fcfa"), c=Sum("cogs_fcfa")).order_by()}
    for r in (_loss_movements(bar, day, day).values("product_bar_id").annotate(q=Sum("quantity")).order_by()):
        p = products.setdefault(r["product_bar_id"], {"qty_sold": ZERO, "revenue_fcfa": 0, "cogs_fcfa": 0, "qty_lost": ZERO})
        p["qty_lost"] = -(r["q"] or ZERO)
    return summary, products


@transaction.atomic
def build_day(bar, day):
    """Enregistre le résumé et les stats produits d'une journée (idempotent). Une journée sans activité
    n'est pas conservée : elle compte comme « bar fermé » pour les prévisions."""
    summary, products = compute_day(bar, day)
    if not (summary["tickets_count"] or summary["losses_fcfa"] or summary["collected_fcfa"]):
        DailySalesSummary.objects.filter(bar=bar, business_date=day).delete()
        ProductDailyStat.objects.filter(bar=bar, business_date=day).delete()
        return None
    obj, _ = DailySalesSummary.objects.update_or_create(bar=bar, business_date=day, defaults=summary)
    for pid, values in products.items():
        ProductDailyStat.objects.update_or_create(bar=bar, product_bar_id=pid, business_date=day, defaults=values)
    ProductDailyStat.objects.filter(bar=bar, business_date=day).exclude(product_bar_id__in=list(products)).delete()
    return obj


def build_range(bar, start, end):
    built, day = 0, start
    while day <= end:
        built += 1 if build_day(bar, day) else 0
        day += timedelta(days=1)
    return built


# ------------------------------------------------------------------ lecture pour les tableaux de bord
def period_totals(bar, start, end):
    r = DailySalesSummary.objects.filter(bar=bar, business_date__range=(start, end)).aggregate(
        days=Count("id"), tickets=Sum("tickets_count"), revenue=Sum("revenue_fcfa"), cogs=Sum("cogs_fcfa"),
        margin=Sum("gross_margin_fcfa"), losses=Sum("losses_fcfa"), collected=Sum("collected_fcfa"),
        credit=Sum("credit_granted_fcfa"))
    t = {k: int(v or 0) for k, v in r.items()}
    t["avg_ticket"] = t["revenue"] // t["tickets"] if t["tickets"] else 0
    t["avg_day"] = t["revenue"] // t["days"] if t["days"] else 0
    t["margin_pct"] = round(t["margin"] * 100 / t["revenue"], 1) if t["revenue"] else None
    return t


def daily_series(bar, start, end):
    """Une entrée par jour (zéros pour les jours sans activité), prête pour un graphique."""
    rows = {s.business_date: s for s in DailySalesSummary.objects.filter(bar=bar, business_date__range=(start, end))}
    series, day = [], start
    while day <= end:
        s = rows.get(day)
        series.append({"date": day.isoformat(), "open": s is not None,
                       "revenue": s.revenue_fcfa if s else 0, "cogs": s.cogs_fcfa if s else 0,
                       "margin": s.gross_margin_fcfa if s else 0, "tickets": s.tickets_count if s else 0,
                       "losses": s.losses_fcfa if s else 0, "collected": s.collected_fcfa if s else 0})
        day += timedelta(days=1)
    return series


def weekday_averages(series):
    """Chiffre d'affaires moyen par jour de la semaine (sur les jours ouverts)."""
    acc = defaultdict(list)
    for s in series:
        if s["open"]:
            acc[date_weekday(s["date"])].append(s["revenue"])
    return [{"weekday": wd, "label": WEEKDAYS[wd], "revenue": sum(acc[wd]) // len(acc[wd]) if acc[wd] else 0,
             "days": len(acc[wd])} for wd in range(7)]


def date_weekday(iso):
    from datetime import date
    return date.fromisoformat(iso).weekday()


def hourly_distribution(bar, start, end):
    """Ventes par heure de la journée (heure locale, calculée en Python pour ne pas dépendre des fuseaux MySQL)."""
    revenue, count = defaultdict(int), defaultdict(int)
    for added_at, total in _lines(bar, start, end).values_list("added_at", "line_total_fcfa"):
        h = timezone.localtime(added_at).hour
        revenue[h] += total
        count[h] += 1
    return [{"hour": h, "revenue": revenue[h], "lines": count[h]} for h in range(24)]


def product_ranking(bar, start, end, sort="revenue", q=""):
    qs = ProductDailyStat.objects.filter(bar=bar, business_date__range=(start, end))
    if q:
        qs = qs.filter(Q(product_bar__product__name__icontains=q) | Q(product_bar__product__brand__icontains=q))
    rows = list(qs.values("product_bar_id", "product_bar__product__name", "product_bar__product__category__name")
                .annotate(qty=Sum("qty_sold"), revenue=Sum("revenue_fcfa"), cogs=Sum("cogs_fcfa"), lost=Sum("qty_lost"))
                .order_by())
    for r in rows:
        r["name"], r["category"] = r.pop("product_bar__product__name"), r.pop("product_bar__product__category__name")
        r["qty"], r["lost"] = r["qty"] or ZERO, r["lost"] or ZERO
        r["revenue"], r["cogs"] = int(r["revenue"] or 0), int(r["cogs"] or 0)
        r["margin"] = r["revenue"] - r["cogs"]
        r["margin_pct"] = round(r["margin"] * 100 / r["revenue"], 1) if r["revenue"] else None
    keys = {"revenue": "revenue", "qty": "qty", "margin": "margin", "lost": "lost"}
    rows.sort(key=lambda r: r[keys.get(sort, "revenue")], reverse=True)
    return rows


# ------------------------------------------------------------------ prévisions
def generate_forecasts(bar):
    """Prévisions des 7 prochains jours : moyenne du même jour de la semaine sur les 8 dernières semaines.
    Par produit : quantité de la semaine, date de rupture probable et quantité à commander.
    Pour le bar : chiffre d'affaires de chaque jour. Retourne le nombre de lignes créées."""
    today = bar.current_business_date()
    start, end = today - timedelta(days=HISTORY_DAYS), today - timedelta(days=1)
    summaries = {s.business_date: s for s in DailySalesSummary.objects.filter(bar=bar, business_date__range=(start, end))}
    open_days = sorted(summaries)
    if len(open_days) < MIN_HISTORY_DAYS:
        return 0
    by_weekday = defaultdict(list)
    for d in open_days:
        by_weekday[d.weekday()].append(d)

    stats = defaultdict(dict)
    for pid, d, q, r in (ProductDailyStat.objects.filter(bar=bar, business_date__range=(start, end))
                         .values_list("product_bar_id", "business_date", "qty_sold", "revenue_fcfa")):
        stats[pid][d] = (float(q), r)
    active = set(ProductBar.objects.filter(bar=bar, is_active=True).values_list("id", flat=True))
    stock = stock_by_product(bar)
    cover = getattr(settings, "ANALYTICS_COVER_DAYS", 14)
    first_day, rows = today + timedelta(days=1), []

    for pid in active & set(stats):
        s = stats[pid]
        week_total = sum(sum(s.get(d, (0, 0))[0] for d in days) / len(days) for days in by_weekday.values())
        if week_total <= 0:
            continue
        qtys = [s.get(d, (0, 0))[0] for d in open_days]
        mean = sum(qtys) / len(qtys)
        cv = statistics.pstdev(qtys) / mean if mean else 1
        confidence = min(1.0, len(open_days) / HISTORY_DAYS) * max(0.0, 1 - min(cv, 1.0))
        total_qty, total_rev = sum(q for q, _ in s.values()), sum(r for _, r in s.values())
        unit_revenue = total_rev / total_qty if total_qty else 0
        avg_daily = week_total / 7
        in_stock = float(stock.get(pid, {}).get("qty", 0))
        stockout = None
        if in_stock <= 0:
            stockout = today
        elif in_stock / avg_daily < 60:
            stockout = today + timedelta(days=int(in_stock / avg_daily))
        need = avg_daily * cover - in_stock
        rows.append(SalesForecast(
            bar=bar, product_bar_id=pid, granularity=PeriodType.WEEK, target_start=first_day, method=METHOD,
            predicted_qty=Decimal(str(round(week_total, 3))), predicted_revenue_fcfa=int(week_total * unit_revenue),
            predicted_stockout_date=stockout, suggested_order_qty=Decimal(math.ceil(need)) if need > 0 else ZERO,
            confidence=Decimal(str(round(confidence, 2)))))

    week_revenue = 0
    for k in range(1, 8):
        day = today + timedelta(days=k)
        samples = by_weekday.get(day.weekday(), [])
        predicted = sum(summaries[d].revenue_fcfa for d in samples) // len(samples) if samples else 0
        week_revenue += predicted
        rows.append(SalesForecast(bar=bar, granularity=PeriodType.DAY, target_start=day, method=METHOD,
                                  predicted_revenue_fcfa=predicted,
                                  confidence=Decimal(str(round(min(1.0, len(samples) / 8), 2)))))
    rows.append(SalesForecast(bar=bar, granularity=PeriodType.WEEK, target_start=first_day, method=METHOD,
                              predicted_revenue_fcfa=week_revenue,
                              confidence=Decimal(str(round(min(1.0, len(open_days) / HISTORY_DAYS), 2)))))
    with transaction.atomic():
        SalesForecast.objects.filter(bar=bar, method=METHOD, target_start__gte=today).delete()
        SalesForecast.objects.bulk_create(rows)
    return len(rows)


def latest_product_forecasts(bar):
    latest = (SalesForecast.objects.filter(bar=bar, granularity=PeriodType.WEEK, product_bar__isnull=False)
              .aggregate(d=Max("target_start"))["d"])
    if latest is None:
        return SalesForecast.objects.none()
    return (SalesForecast.objects.filter(bar=bar, granularity=PeriodType.WEEK, product_bar__isnull=False,
                                         target_start=latest).select_related("product_bar__product__category"))


# ------------------------------------------------------------------ recommandations
def _upsert(bar, kind, product_bar_id, title, message, priority, payload, valid_days):
    """Crée la recommandation, ou met à jour celle déjà active. Une recommandation appliquée ou ignorée
    depuis moins de 7 jours n'est pas recréée (on ne harcèle pas le gérant). Retourne l'objet créé ou None."""
    Status = Recommendation.Status
    cid = payload.get("customer_id")
    same = [r for r in Recommendation.objects.filter(bar=bar, kind=kind, product_bar_id=product_bar_id)
            if r.payload.get("customer_id") == cid]
    recent = timezone.now() - timedelta(days=7)
    if any(r.status in (Status.APPLIED, Status.DISMISSED) and r.updated_at >= recent for r in same):
        return None
    valid_until = bar.current_business_date() + timedelta(days=valid_days)
    active = [r for r in same if r.status in (Status.NEW, Status.SEEN)]
    if active:
        r = active[0]
        r.title, r.message, r.priority, r.payload, r.valid_until = title, message, priority, payload, valid_until
        r.save(update_fields=["title", "message", "priority", "payload", "valid_until", "updated_at"])
        return None
    return Recommendation.objects.create(bar=bar, kind=kind, product_bar_id=product_bar_id, title=title[:150],
                                         message=message, priority=priority, payload=payload,
                                         valid_until=valid_until, generated_by="RULES")


def expire_recommendations(bar):
    today = bar.current_business_date()
    return (Recommendation.objects.filter(bar=bar, valid_until__lt=today,
                                          status__in=(Recommendation.Status.NEW, Recommendation.Status.SEEN))
            .update(status=Recommendation.Status.DISMISSED))


def _quiet_hours(hours):
    """Plus longue plage d'heures creuses (moins de 25 % de l'heure de pointe) parmi les heures actives."""
    active = {h["hour"]: h["revenue"] for h in hours if h["revenue"] > 0}
    if len(active) < 6:
        return None
    limit = max(active.values()) * 0.25
    quiet = sorted(h for h, r in active.items() if r < limit)
    best, run = [], []
    for h in quiet:
        run = run + [h] if run and h == run[-1] + 1 else [h]
        if len(run) > len(best):
            best = run
    return (best[0], best[-1] + 1) if best else None


def generate_recommendations(bar):
    """Recommandations par règles simples (sans IA). Retourne la liste des NOUVELLES recommandations."""
    expire_recommendations(bar)
    today = bar.current_business_date()
    start, end = today - timedelta(days=30), today - timedelta(days=1)
    created = []

    def add(*args, **kwargs):
        r = _upsert(bar, *args, **kwargs)
        if r:
            created.append(r)

    products = {pb.id: pb for pb in ProductBar.objects.filter(bar=bar, is_active=True).select_related("product__category")}
    sold = {r["product_bar_id"]: r for r in product_ranking_ids(bar, start, end)}
    stock = stock_by_product(bar)
    forecasts = {f.product_bar_id: f for f in latest_product_forecasts(bar)}
    K = Recommendation.Kind

    for pid, pb in products.items():
        name, s = str(pb.product), sold.get(pid)
        in_stock = stock.get(pid, {"qty": ZERO, "value": ZERO})["qty"]
        f = forecasts.get(pid)
        avg_daily = float(f.predicted_qty) / 7 if f and f.predicted_qty else (float(s["qty"]) / 30 if s else 0)
        days_cover = float(in_stock) / avg_daily if avg_daily else None

        if avg_daily and (in_stock <= pb.low_stock_threshold or (days_cover is not None and days_cover <= 7)):
            suggested = f.suggested_order_qty if f and f.suggested_order_qty else Decimal(math.ceil(avg_daily * 14))
            urgent = in_stock <= 0 or (days_cover is not None and days_cover <= 2)
            add(K.RESTOCK, pid, f"{'Rupture' if in_stock <= 0 else 'Réapprovisionner'} : {name}",
                f"Il reste {in_stock.normalize():f} unité(s), soit environ {int(days_cover or 0)} jour(s) de vente. "
                f"Commande conseillée : {suggested.normalize():f} unité(s).",
                1 if urgent else 2, {"stock": float(in_stock), "days_cover": round(days_cover or 0, 1),
                                     "suggested_qty": float(suggested)}, 3)

        old_enough = pb.created_at.date() <= today - timedelta(days=30)
        if in_stock > 0 and ((not avg_daily and old_enough) or (days_cover is not None and days_cover > 120)):
            value = int(stock.get(pid, {}).get("value", 0))
            add(K.SLOW_MOVER, pid, f"Faible rotation : {name}",
                f"{in_stock.normalize():f} unité(s) en stock ({value} FCFA immobilisés) pour très peu de ventes. "
                "Pensez à une promotion ou à ne pas recommander ce produit.", 3,
                {"stock": float(in_stock), "value": value}, 14)

        if s and s["qty"] >= 5 and s["margin_pct"] is not None and s["margin_pct"] < 15:
            add(K.PRICE_REVIEW, pid, f"Marge faible : {name}",
                f"Marge de {s['margin_pct']} % sur 30 jours ({s['margin']} FCFA). Revoyez le prix de vente ou le prix d'achat.",
                2 if s["margin_pct"] < 5 else 3, {"margin_pct": s["margin_pct"]}, 14)

    ranked = sorted(sold.values(), key=lambda r: r["qty"])
    if len(ranked) >= 6:
        median_qty = ranked[len(ranked) // 2]["qty"]
        picks = [r for r in ranked if r["qty"] <= median_qty and r["margin_pct"] and r["margin_pct"] >= 40]
        for r in sorted(picks, key=lambda r: r["margin"], reverse=True)[:5]:
            add(K.PROMOTE, r["product_bar_id"], f"À mettre en avant : {r['name']}",
                f"Très bonne marge ({r['margin_pct']} %) mais peu vendu ({r['qty'].normalize():f} unités en 30 jours). "
                "Proposez-le plus souvent aux clients.", 3, {"margin_pct": r["margin_pct"]}, 14)

    quiet = _quiet_hours(hourly_distribution(bar, start, end))
    if quiet:
        add(K.HAPPY_HOUR, None, f"Promotion horaire entre {quiet[0]}h et {quiet[1]}h",
            f"Les ventes sont très faibles entre {quiet[0]}h et {quiet[1]}h par rapport à l'heure de pointe. "
            "Une offre sur cette plage peut attirer des clients.", 4, {"from": quiet[0], "to": quiet[1]}, 14)

    if apps.is_installed("credits"):
        _credit_risks(bar, today, add, K)
    return created


def product_ranking_ids(bar, start, end):
    rows = product_ranking(bar, start, end)
    for r in rows:
        r["product_bar_id"] = r["product_bar_id"]
    return rows


def _credit_risks(bar, today, add, K):
    from credits.models import CustomerCredit
    per = defaultdict(lambda: {"debt": 0, "oldest": None, "customer": None})
    for c in CustomerCredit.objects.filter(bar=bar, status__in=(CustomerCredit.Status.OPEN, CustomerCredit.Status.PARTIAL)
                                           ).select_related("customer"):
        p = per[c.customer_id]
        p["customer"], p["debt"] = c.customer, p["debt"] + c.balance_fcfa
        if c.due_date and c.due_date < today and (p["oldest"] is None or c.due_date < p["oldest"]):
            p["oldest"] = c.due_date
    risky = []
    for cid, p in per.items():
        late = (today - p["oldest"]).days if p["oldest"] else 0
        limit = p["customer"].credit_limit_fcfa
        if late >= 30 or (limit and p["debt"] >= 0.8 * limit):
            risky.append((p["debt"], cid, p, late, limit))
    for debt, cid, p, late, limit in sorted(risky, key=lambda r: r[0], reverse=True)[:5]:
        reasons = []
        if late >= 30:
            reasons.append(f"impayé depuis {late} jours")
        if limit and debt >= 0.8 * limit:
            reasons.append(f"plafond de crédit atteint à {int(debt * 100 / limit)} %")
        add(K.CREDIT_RISK, None, f"Risque de crédit : {p['customer'].name}",
            f"Doit {debt} FCFA ({', '.join(reasons)}). Relancez ce client avant toute nouvelle vente à crédit.",
            2 if late >= 60 else 3, {"customer_id": cid, "debt": debt, "overdue_days": late}, 7)


def set_recommendation_status(recommendation, status):
    allowed = (Recommendation.Status.SEEN, Recommendation.Status.APPLIED, Recommendation.Status.DISMISSED)
    if status not in allowed:
        raise ValueError("Statut invalide.")
    recommendation.status = status
    recommendation.save(update_fields=["status", "updated_at"])
    return recommendation


# ------------------------------------------------------------------ nettoyage
def purge_old(days_forecast=90, days_recommendation=180):
    today = timezone.localdate()
    f = SalesForecast.objects.filter(target_start__lt=today - timedelta(days=days_forecast)).delete()[0]
    r = (Recommendation.objects.filter(updated_at__lt=timezone.now() - timedelta(days=days_recommendation),
                                       status__in=(Recommendation.Status.APPLIED, Recommendation.Status.DISMISSED))
         .delete()[0])
    return {"forecasts": f, "recommendations": r}