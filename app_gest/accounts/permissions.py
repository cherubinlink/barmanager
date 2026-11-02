class Perm:
    POS_SELL = "pos.sell"
    POS_FINALIZE = "pos.finalize"
    POS_DISCOUNT = "pos.discount"
    POS_VOID = "pos.void"
    POS_VALIDATE_QR = "pos.validate_qr_order"
    STOCK_VIEW = "stock.view"
    STOCK_RECEIVE = "stock.receive"
    STOCK_ADJUST = "stock.adjust"
    LOSS_DECLARE = "loss.declare"
    LOSS_APPROVE = "loss.approve"
    PURCHASE_MANAGE = "purchase.manage"
    CREDIT_MANAGE = "credit.manage"
    PRICE_EDIT = "catalog.edit_price"
    CATALOG_ADD = "catalog.add_product"
    REPORT_VIEW = "report.view"
    USER_MANAGE = "users.manage"
    CHAT_USE = "chat.use"
    CHAT_BROADCAST = "chat.broadcast"
    BAR_SETTINGS = "bar.settings"
    SUBSCRIPTION_MANAGE = "bar.subscription"


# code -> (libellé, permissions) ; "*" = toutes. Le gérant peut créer d'autres rôles.
DEFAULT_ROLES = {
    "gerant": ("Gérant", ["*"]),
    "caissier": ("Caissier", [
        Perm.POS_SELL, Perm.POS_FINALIZE, Perm.POS_DISCOUNT, Perm.POS_VALIDATE_QR,
        Perm.CREDIT_MANAGE, Perm.LOSS_DECLARE, Perm.CHAT_USE]),
    "vendeuse": ("Vendeuse / Serveuse", [
        Perm.POS_SELL, Perm.POS_VALIDATE_QR, Perm.LOSS_DECLARE, Perm.CHAT_USE]),
    "magasinier": ("Magasinier", [
        Perm.STOCK_VIEW, Perm.STOCK_RECEIVE, Perm.LOSS_DECLARE, Perm.PURCHASE_MANAGE, Perm.CHAT_USE]),
}
