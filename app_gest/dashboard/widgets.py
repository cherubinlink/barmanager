from datetime import timedelta
from decimal import Decimal

from django.apps import apps
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce

from accounts.models import BarMembership
from catalog.models import ProductBar
from core.models import PaymentMethod
from inventory.models import LossReport, StockLot
from purchasing.models import PurchaseOrder
from sales.models import Payment, Ticket, TicketLine

ZERO = Decimal("0")
OPEN_STATUSES = (Ticket.Status.OPEN, Ticket.Status.AWAITING_PAYMENT)
NOT_COUNTED = (Ticket.Status.CANCELLED, Ticket.Status.PENDING_VALIDATION)


def _credit_model():
    """L'app des créances s'appelle `credits` ou `creances` selon votre choix."""
    for label in ("creances", "credits"):
        try:
            return apps.get_model(label, "CustomerCredit")
        except LookupError:
            continue
    return None


def sales_today(bar, day):
    tickets = Ticket.objects.filter(bar=bar, business_date=day).exclude(status__in=NOT_COUNTED)
    agg = tickets.aggregate(n=Count("id"), revenue=Sum("total_fcfa"), collected=Sum("amount_paid_fcfa"))
    cogs = (TicketLine.objects.filter(ticket__bar=bar, ticket__business_date=day, is_void=False)
            .exclude(ticket__status__in=NOT_COUNTED).aggregate(c=Sum("cogs_fcfa"))["c"] or ZERO)
    revenue, collected = agg["revenue"] or 0, agg["collected"] or 0
    return {"tickets": agg["n"], "revenue": revenue, "collected": collected,
            "balance": revenue - collected, "margin": revenue - int(cogs)}


def my_sales(bar, day, user):
    agg = (Ticket.objects.filter(bar=bar, business_date=day, opened_by=user)
           .exclude(status__in=NOT_COUNTED).aggregate(n=Count("id"), revenue=Sum("total_fcfa")))
    return {"tickets": agg["n"], "revenue": agg["revenue"] or 0}


def open_tickets(bar, limit=10):
    return list(Ticket.objects.filter(bar=bar, status__in=OPEN_STATUSES)
                .select_related("customer").order_by("created_at")[:limit])


def qr_pending(bar, limit=10):
    return list(Ticket.objects.filter(bar=bar, status=Ticket.Status.PENDING_VALIDATION)
                .order_by("created_at")[:limit])


def sales_week(bar, day):
    start = day - timedelta(days=6)
    rows = (Ticket.objects.filter(bar=bar, business_date__gte=start, business_date__lte=day)
            .exclude(status__in=NOT_COUNTED).values("business_date")
            .annotate(rev=Sum("total_fcfa")).order_by())
    by_day = {r["business_date"]: r["rev"] or 0 for r in rows}
    days = [start + timedelta(days=i) for i in range(7)]
    peak = max([by_day.get(d, 0) for d in days] + [1])
    return [{"date": d, "revenue": by_day.get(d, 0), "pct": round(by_day.get(d, 0) * 100 / peak)}
            for d in days]


def top_products(bar, day, days=7, limit=5):
    rows = (TicketLine.objects
            .filter(ticket__bar=bar, ticket__business_date__gte=day - timedelta(days=days - 1),
                    ticket__business_date__lte=day, is_void=False)
            .exclude(ticket__status__in=NOT_COUNTED)
            .values("product_bar__product__name", "product_bar__product__volume_cl")
            .annotate(qty=Sum("quantity"), revenue=Sum("line_total_fcfa")).order_by("-qty")[:limit])
    return [{"name": r["product_bar__product__name"], "volume": r["product_bar__product__volume_cl"],
             "qty": r["qty"], "revenue": r["revenue"] or 0} for r in rows]


def low_stock(bar, limit=8):
    return list(ProductBar.objects.filter(bar=bar, is_active=True)
                .annotate(stock=Coalesce(
                    Sum("lots__remaining_qty", filter=Q(lots__status="OPEN")), Value(ZERO),
                    output_field=DecimalField(max_digits=14, decimal_places=3)))
                .filter(stock__lte=F("low_stock_threshold"))
                .select_related("product").order_by("stock")[:limit])


def stock_value(bar):
    value = StockLot.objects.filter(bar=bar, status=StockLot.Status.OPEN).aggregate(
        v=Sum(ExpressionWrapper(F("remaining_qty") * F("unit_cost_fcfa"),
                                output_field=DecimalField(max_digits=18, decimal_places=2))))["v"]
    return int(value or 0)


def receivables(bar, day):
    Credit = _credit_model()
    if Credit is None:
        return None
    qs = Credit.objects.filter(bar=bar, status__in=("OPEN", "PARTIAL"))
    agg = qs.aggregate(total=Sum("amount_fcfa"), paid=Sum("amount_paid_fcfa"))
    overdue = qs.filter(due_date__lt=day).select_related("customer").order_by("due_date")
    return {"balance": (agg["total"] or 0) - (agg["paid"] or 0), "count": qs.count(),
            "overdue_count": overdue.count(), "overdue": list(overdue[:5])}


def payables(bar, day):
    qs = (PurchaseOrder.objects.filter(bar=bar)
          .exclude(status__in=(PurchaseOrder.Status.CANCELLED, PurchaseOrder.Status.DRAFT))
          .exclude(payment_status=PurchaseOrder.PaymentStatus.PAID))
    agg = qs.aggregate(total=Sum("total_fcfa"), paid=Sum("amount_paid_fcfa"))
    return {"balance": (agg["total"] or 0) - (agg["paid"] or 0), "count": qs.count(),
            "due_soon": qs.filter(due_date__lte=day + timedelta(days=7)).count()}


def purchase_to_receive(bar, limit=6):
    return list(PurchaseOrder.objects
                .filter(bar=bar, status__in=(PurchaseOrder.Status.SENT, PurchaseOrder.Status.PARTIAL))
                .select_related("supplier").order_by("expected_at", "id")[:limit])


def recent_receptions(bar, limit=5):
    return list(PurchaseOrder.objects.filter(bar=bar, received_at__isnull=False)
                .select_related("supplier").order_by("-received_at")[:limit])


def pending_losses(bar, limit=6):
    qs = LossReport.objects.filter(bar=bar, status=LossReport.Status.PENDING)
    return {"count": qs.count(),
            "items": list(qs.select_related("product_bar__product", "declared_by")[:limit])}


def payments_by_method(bar, day):
    rows = (Payment.objects.filter(bar=bar, ticket__business_date=day)
            .values("method", "kind").annotate(total=Sum("amount_fcfa")).order_by())
    totals = {}
    for r in rows:
        sign = -1 if r["kind"] == Payment.Kind.REFUND else 1
        totals[r["method"]] = totals.get(r["method"], 0) + sign * r["total"]
    return {"items": [{"label": PaymentMethod(m).label, "total": t} for m, t in totals.items()],
            "total": sum(totals.values())}


def team(bar):
    return {"count": BarMembership.objects.filter(bar=bar, is_active=True).count()}