from decimal import Decimal

from django.apps import apps
from django.db import transaction
from django.utils import timezone

from core.models import AuditLog
from inventory.models import StockLot, StockMovement

from .models import PurchaseOrder


class ReceptionError(Exception):
    pass


def fully_received(order):
    lines = list(order.lines.all())
    return bool(lines) and all(l.received_packages >= l.quantity_packages for l in lines)


def has_receptions(order):
    return order.lines.filter(received_packages__gt=0).exists()


def refresh_order_status(order):
    """« Clôturée » dès que tout est reçu ET payé ; la commande se rouvre si un paiement est annulé."""
    Status, Pay = PurchaseOrder.Status, PurchaseOrder.PaymentStatus
    if order.status == Status.RECEIVED and order.payment_status == Pay.PAID:
        order.status = Status.CLOSED
    elif order.status == Status.CLOSED and order.payment_status != Pay.PAID and fully_received(order):
        order.status = Status.RECEIVED
    else:
        return
    order.save(update_fields=["status", "updated_at"])


def audit(request, action, target, **payload):
    AuditLog.objects.create(bar=request.bar, actor=request.user, action=action,
                            target_model=type(target).__name__, target_id=str(target.pk), payload=payload)


def notify_purchasers(order, title, exclude_user=None, level=None):
    if not apps.is_installed("notifications"):
        return
    from accounts.permissions import Perm
    from notifications.models import Notification, NotificationType
    from notifications.services import notify_bar

    notify_bar(order.bar, type=NotificationType.PURCHASE_RECEIVED, title=title,
               perm=Perm.PURCHASE_MANAGE, exclude_user=exclude_user,
               level=level or Notification.Level.INFO, url=f"/achats/{order.pk}/")


@transaction.atomic
def receive_order(order, quantities, user):
    """Réceptionne des conditionnements : chaque réception crée un LOT de stock (FIFO) avec son
    prix d'achat, et un mouvement d'entrée. `quantities` = {id_ligne: nb de conditionnements reçus}."""
    order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
    if order.status not in (PurchaseOrder.Status.SENT, PurchaseOrder.Status.PARTIAL):
        raise ReceptionError("Cette commande ne peut plus être réceptionnée.")
    lines = {l.id: l for l in order.lines.select_for_update()}
    now, day, created = timezone.now(), order.bar.current_business_date(), 0
    for line_id, qty in quantities.items():
        line = lines[line_id]
        if qty > line.quantity_packages - line.received_packages:
            raise ReceptionError("Quantité supérieure au reste à recevoir.")
        units = Decimal(qty * line.units_per_package)
        cost = line.unit_cost_fcfa.quantize(Decimal("0.01"))
        lot = StockLot.objects.create(
            bar=order.bar, product_bar=line.product_bar, purchase_line=line,
            source=StockLot.Source.PURCHASE, received_at=now, initial_qty=units,
            remaining_qty=units, unit_cost_fcfa=cost)
        StockMovement.objects.create(
            bar=order.bar, product_bar=line.product_bar, lot=lot, kind=StockMovement.Kind.PURCHASE_IN,
            quantity=units, unit_cost_fcfa=cost, occurred_at=now, business_date=day,
            created_by=user, note=f"Réception {order.reference}")
        line.received_packages += qty
        line.save(update_fields=["received_packages"])
        created += 1
    if not created:
        raise ReceptionError("Aucune quantité reçue.")
    complete = all(l.received_packages >= l.quantity_packages for l in lines.values())
    order.status = PurchaseOrder.Status.RECEIVED if complete else PurchaseOrder.Status.PARTIAL
    order.received_at = now
    order.save(update_fields=["status", "received_at", "updated_at"])
    refresh_order_status(order)
    return order