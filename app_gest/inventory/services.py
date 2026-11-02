from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from inventory.models import StockLot, StockMovement


class InsufficientStock(Exception):
    pass


@transaction.atomic
def consume_stock(*, bar, product_bar, qty, kind, ticket_line=None, loss_report=None,
                  user=None, allow_negative=False):
    """Sort `qty` unités en vidant d'abord le lot le plus ancien (FIFO).

    Retourne (mouvements, coût_des_marchandises_vendues). Verrouille les lots
    (select_for_update) : deux vendeuses ne peuvent pas vendre la dernière bouteille.
    """
    to_take = Decimal(qty)
    movements, cogs = [], Decimal("0")
    business_date = bar.current_business_date()

    for lot in StockLot.objects.fifo(bar, product_bar):
        if to_take <= 0:
            break
        take = min(lot.remaining_qty, to_take)
        lot.remaining_qty -= take
        if lot.remaining_qty == 0:
            lot.status = StockLot.Status.DEPLETED
        lot.save(update_fields=["remaining_qty", "status", "updated_at"])
        movements.append(StockMovement.objects.create(
            bar=bar, product_bar=product_bar, lot=lot, kind=kind, quantity=-take,
            unit_cost_fcfa=lot.unit_cost_fcfa, ticket_line=ticket_line,
            loss_report=loss_report, created_by=user,
            occurred_at=timezone.now(), business_date=business_date,
        ))
        cogs += take * lot.unit_cost_fcfa
        to_take -= take

    if to_take > 0:
        if not allow_negative:
            raise InsufficientStock(f"Stock insuffisant pour {product_bar} (manque {to_take}).")
        cost = Decimal(product_bar.purchase_price_fcfa)  # lot inconnu : dernier prix d'achat
        movements.append(StockMovement.objects.create(
            bar=bar, product_bar=product_bar, lot=None, kind=kind, quantity=-to_take,
            unit_cost_fcfa=cost, ticket_line=ticket_line, loss_report=loss_report,
            created_by=user, occurred_at=timezone.now(), business_date=business_date,
            note="Vente hors stock enregistré (à régulariser)",
        ))
        cogs += to_take * cost
    return movements, cogs
