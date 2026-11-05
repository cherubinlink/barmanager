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

PERMISSION_GROUPS = {
    "Ventes": [
        (Perm.POS_SELL, "Créer et modifier les tickets"),
        (Perm.POS_FINALIZE, "Encaisser et finaliser les factures"),
        (Perm.POS_DISCOUNT, "Accorder des remises"),
        (Perm.POS_VOID, "Annuler des lignes ou des tickets"),
        (Perm.POS_VALIDATE_QR, "Valider les commandes QR des clients"),
    ],
    "Stock": [
        (Perm.STOCK_VIEW, "Voir le stock"),
        (Perm.STOCK_RECEIVE, "Réceptionner les commandes fournisseurs"),
        (Perm.STOCK_ADJUST, "Faire l'inventaire et ajuster le stock"),
    ],
    "Pertes": [
        (Perm.LOSS_DECLARE, "Déclarer une perte"),
        (Perm.LOSS_APPROVE, "Valider les pertes"),
    ],
    "Achats et crédits": [
        (Perm.PURCHASE_MANAGE, "Gérer les commandes fournisseurs"),
        (Perm.CREDIT_MANAGE, "Gérer les crédits clients"),
    ],
    "Catalogue": [
        (Perm.PRICE_EDIT, "Modifier les prix"),
        (Perm.CATALOG_ADD, "Ajouter des produits"),
    ],
    "Gestion": [
        (Perm.REPORT_VIEW, "Voir les rapports et statistiques"),
        (Perm.USER_MANAGE, "Gérer l'équipe et les rôles"),
        (Perm.BAR_SETTINGS, "Modifier les réglages du bar"),
        (Perm.SUBSCRIPTION_MANAGE, "Gérer l'abonnement"),
    ],
    "Messagerie": [
        (Perm.CHAT_USE, "Utiliser la messagerie"),
        (Perm.CHAT_BROADCAST, "Écrire à toute l'équipe"),
    ],
}