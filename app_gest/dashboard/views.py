from django.shortcuts import render
from django.urls import NoReverseMatch, reverse

from accounts.decorators import bar_required
from accounts.permissions import Perm

from dashboard import widgets as w

# nom du bloc -> fonction qui calcule ses données
WIDGETS = {
    "sales_today": lambda bar, day, user: w.sales_today(bar, day),
    "my_sales": lambda bar, day, user: w.my_sales(bar, day, user),
    "open_tickets": lambda bar, day, user: w.open_tickets(bar),
    "qr_pending": lambda bar, day, user: w.qr_pending(bar),
    "sales_week": lambda bar, day, user: w.sales_week(bar, day),
    "top_products": lambda bar, day, user: w.top_products(bar, day),
    "low_stock": lambda bar, day, user: w.low_stock(bar),
    "stock_value": lambda bar, day, user: w.stock_value(bar),
    "receivables": lambda bar, day, user: w.receivables(bar, day),
    "payables": lambda bar, day, user: w.payables(bar, day),
    "purchase_to_receive": lambda bar, day, user: w.purchase_to_receive(bar),
    "recent_receptions": lambda bar, day, user: w.recent_receptions(bar),
    "pending_losses": lambda bar, day, user: w.pending_losses(bar),
    "payments_by_method": lambda bar, day, user: w.payments_by_method(bar, day),
    "team": lambda bar, day, user: w.team(bar),
}

# Chaque permission ouvre des blocs : le tableau de bord s'adapte à TOUS les rôles,
# y compris ceux que le gérant crée lui-même.
PERM_WIDGETS = [
    (Perm.REPORT_VIEW, ["sales_today", "sales_week", "top_products", "payables", "stock_value", "team"]),
    (Perm.POS_FINALIZE, ["sales_today", "payments_by_method"]),
    (Perm.POS_SELL, ["my_sales", "open_tickets"]),
    (Perm.POS_VALIDATE_QR, ["qr_pending"]),
    (Perm.CREDIT_MANAGE, ["receivables"]),
    (Perm.STOCK_VIEW, ["low_stock"]),
    (Perm.STOCK_RECEIVE, ["purchase_to_receive", "recent_receptions"]),
    (Perm.PURCHASE_MANAGE, ["purchase_to_receive"]),
    (Perm.LOSS_APPROVE, ["pending_losses"]),
]

ROLE_INTRO = {
    "gerant": ("Vue d'ensemble ", "Ventes du jour, stock, crédits et décisions à prendre."),
    "caissier": ("Caisse", "Encaissements du jour et factures en attente."),
    "vendeuse": ("Service", "Vos commandes en cours et les commandes QR à valider."),
    "magasinier": ("Stock", "Niveaux de stock, commandes à réceptionner et pertes."),
    "default": ("Tableau de bord", "Les informations utiles pour votre rôle."),
}

# (libellé, icône, nom d'URL, permission). Le bouton reste grisé tant que l'URL n'existe pas.
QUICK_ACTIONS = [
    ("Nouveau ticket", "🧾", "sales:ticket_create", Perm.POS_SELL),
    ("Commandes QR", "📱", "sales:ticket_list", Perm.POS_VALIDATE_QR),
    ("Encaisser", "💵", "sales:ticket_list", Perm.POS_FINALIZE),
    ("Déclarer une perte", "🍾", "inventory:loss_create", Perm.LOSS_DECLARE),
    ("Valider les pertes", "✅", "inventory:loss_list", Perm.LOSS_APPROVE),
    ("Réceptionner", "📦", "purchasing:order_list", Perm.STOCK_RECEIVE),
    ("Commander au dépôt", "🚚", "purchasing:order_create", Perm.PURCHASE_MANAGE),
    ("Inventaire", "📋", "inventory:count_list", Perm.STOCK_ADJUST),
    ("Crédits", "💳", "credits:credit_list", Perm.CREDIT_MANAGE),
    ("Produits et prix", "🍺", "catalog:product_list", Perm.PRICE_EDIT),
    ("Équipe", "👥", "accounts:team", Perm.USER_MANAGE),
    ("Rôles", "🛡️", "accounts:roles", Perm.USER_MANAGE),
    ("Réglages du bar", "⚙️", "tenants:settings", Perm.BAR_SETTINGS),
    ("QR code du bar", "🔳", "tenants:qr", Perm.BAR_SETTINGS),
    ("Abonnement", "🔑", "tenants:subscription", Perm.SUBSCRIPTION_MANAGE),
    ("Messagerie", "💬", "chat:conversation_list", Perm.CHAT_USE),
    ("Statistiques", "📈", "analytics:dashboard", Perm.REPORT_VIEW),
]


def _url(name):
    try:
        return reverse(name)
    except NoReverseMatch:
        return ""


@bar_required()
def homes(request):
    bar, membership = request.bar, request.membership
    day = bar.current_business_date()

    wanted = []
    for perm, names in PERM_WIDGETS:
        if membership.has_perm(perm):
            wanted += [n for n in names if n not in wanted]
    data = {name: WIDGETS[name](bar, day, request.user) for name in wanted}

    role_key = "gerant" if membership.is_owner else membership.role.code
    title, intro = ROLE_INTRO.get(role_key, ROLE_INTRO["default"])
    title = bar.name
    actions = [{"label": label, "icon": icon, "url": _url(name)}
               for label, icon, name, perm in QUICK_ACTIONS if membership.has_perm(perm)]

    ADD_MEMBER_URL_NAME = "accounts:member_create"   # remplacez par le vrai nom de votre URL

    # dans homes(), avant le return :
    add_member_url = ""
    if membership.has_perm(Perm.USER_MANAGE):
        add_member_url = _url(ADD_MEMBER_URL_NAME) or _url("accounts:team")

    context = {
        "day": day, 
        "data": data, 
        "title": title, 
        "intro": intro, 
        "actions": actions, 
        "add_member_url": add_member_url,
    }
    return render(request, "dashboard/homes.html",context )