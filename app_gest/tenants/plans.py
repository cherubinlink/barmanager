"""Grille tarifaire : options de chaque formule et préparation de leur affichage.

Chaque formule reprend les options de la précédente et en ajoute (comme sur la grille tarifaire).
"""

UNLIMITED = None   # utilisateurs illimités ; mettez 0 si votre champ max_users n'accepte pas null

STARTER = ["products", "categories", "sales", "sales_history", "stock", "losses", "purchases", "credits",
           "qr_menu", "qr_orders", "chat", "roles", "basic_dashboard"]
BUSINESS = STARTER + ["suppliers", "customers", "expenses", "profit_tracking", "periodic_reports",
                      "exports", "chat_broadcast", "cash_registers","forecasts"]
PREMIUM = BUSINESS + [ "waiters", "performance", "stock_alerts", "advanced_reports",
                      "recommendations"]
ENTERPRISE = PREMIUM + ["multi_cash", "advanced_roles", "multi_establishments", "consolidated_reports",
                        "activity_log", "strategic_dashboard", "priority_support"]

# clé -> libellé affiché (l'ordre ici est l'ordre d'affichage)
FEATURE_LABELS = {
    # --- Starter ---
    "products": "Gestion des produits",
    "categories": "Gestion des catégories",
    "sales": "Caisse, tickets et gestion des ventes",
    "sales_history": "Historique des ventes",
    "stock": "Gestion du stock et inventaire",
    "losses": "Gestion des pertes et produits cassés",
    "purchases": "Gestion des achats et commandes fournisseurs",
    "credits": "Gestion des crédits clients",
    "qr_menu": "Menu et prix par QR code",
    "qr_orders": "Commandes des clients par QR code",
    "chat": "Messagerie d'équipe",
    "roles": "Rôles et permissions",
    "basic_dashboard": "Tableau de bord simple",
    # --- Business ---
    "cash_registers": "Gestion des caisses",
    "suppliers": "Gestion des fournisseurs",
    "customers": "Gestion des clients",
    "expenses": "Gestion des dépenses",
    "profit_tracking": "Suivi des bénéfices",
    "periodic_reports": "Rapports journaliers et mensuels",
    "exports": "Export Excel, PDF et CSV",
    "chat_broadcast": "Messages à toute l'équipe",
    "forecasts": "Prévisions de ventes et de ruptures",
    # --- Premium ---
    
    "waiters": "Gestion des serveurs",
    "performance": "Suivi des performances",
    "stock_alerts": "Alertes de stock",
    "advanced_reports": "Rapports avancés",
    "recommendations": "Recommandations automatiques",
    # --- Enterprise ---
    "multi_cash": "Multi-caisses",
    "advanced_roles": "Gestion avancée des rôles et permissions",
    "multi_establishments": "Gestion multi-établissements",
    "consolidated_reports": "Consolidation des rapports",
    "activity_log": "Journal des activités",
    "strategic_dashboard": "Tableau de bord stratégique",
    "priority_support": "Assistance prioritaire",
}

PLAN_CATALOG = [
    {"code": "starter", "name": "Starter", "price_fcfa": 2000, "duration_days": 30, "max_users": 3,
     "sort_order": 1, "features": STARTER, "description": "Tout pour gérer un petit bar au quotidien."},
    {"code": "business", "name": "Business", "price_fcfa": 5000, "duration_days": 30, "max_users": 8,
     "sort_order": 2, "features": BUSINESS,
     "description": "Fournisseurs, dépenses, bénéfices et prévisions pour piloter votre activité."},
    {"code": "premium", "name": "Premium", "price_fcfa": 10000, "duration_days": 30, "max_users": 20,
     "sort_order": 3, "features": PREMIUM,
     "description": "Caisses, serveurs, performances et conseils automatiques pour les grandes équipes."},
    {"code": "enterprise", "name": "Enterprise", "price_fcfa": 25000, "duration_days": 30, "max_users": None,
     "sort_order": 4, "features": ENTERPRISE,                 # None = utilisateurs illimités
     "description": "Plusieurs établissements, rapports consolidés et assistance prioritaire."},
]


def feature_flags(enabled):
    """Dictionnaire complet {option: vrai/faux}, au format du champ Plan.features."""
    return {key: key in enabled for key in FEATURE_LABELS}


def annotate_plans(plans):
    """Prépare l'affichage : pour chaque formule, ses nouvelles options par rapport à la précédente.

    Les formules doivent arriver triées de la moins chère à la plus chère :
    Plan.objects.filter(is_active=True).order_by("price_fcfa").
    Ajoute à chaque formule : new_features (libellés) et inherits_from (nom de la formule précédente).
    """
    plans = list(plans)
    previous = None
    for plan in plans:
        flags = plan.features or {}
        before = (previous.features or {}) if previous else {}
        plan.new_features = [label for key, label in FEATURE_LABELS.items()
                             if flags.get(key) and not before.get(key)]
        plan.inherits_from = previous.name if previous else ""
        previous = plan
    return plans