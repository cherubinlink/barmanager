"""Grille tarifaire : options de chaque formule et préparation de leur affichage.

Chaque formule reprend les options de la précédente et en ajoute (comme sur la grille tarifaire).
"""

UNLIMITED = None   # utilisateurs illimités ; mettez 0 si votre champ max_users n'accepte pas null

STARTER = ["products", "sales", "stock", "categories", "sales_history", "basic_dashboard"]
BUSINESS = STARTER + ["suppliers", "purchases", "expenses", "profit_tracking", "periodic_reports", "customers"]
PREMIUM = BUSINESS + ["cash_registers", "waiters", "performance", "credits", "stock_alerts",
                      "losses", "exports", "advanced_reports"]
ENTERPRISE = PREMIUM + ["multi_cash", "advanced_roles", "multi_establishments",
                        "consolidated_reports", "activity_log", "strategic_dashboard", "priority_support"]

# clé -> libellé affiché (l'ordre ici est l'ordre d'affichage)
FEATURE_LABELS = {
    # Starter
    "products": "Gestion des produits",
    "sales": "Gestion des ventes",
    "stock": "Gestion du stock",
    "categories": "Gestion des catégories",
    "sales_history": "Historique des ventes",
    "basic_dashboard": "Tableau de bord simple",
    # Business
    "suppliers": "Gestion des fournisseurs",
    "purchases": "Gestion des achats",
    "expenses": "Gestion des dépenses",
    "profit_tracking": "Suivi des bénéfices",
    "periodic_reports": "Rapports journaliers et mensuels",
    "customers": "Gestion des clients",
    # Premium
    "cash_registers": "Gestion des caisses",
    "waiters": "Gestion des serveurs",
    "performance": "Suivi des performances",
    "credits": "Gestion des crédits clients",
    "stock_alerts": "Alertes de stock",
    "losses": "Gestion des pertes et produits cassés",
    "exports": "Export Excel et PDF",
    "advanced_reports": "Rapports avancés",
    # Enterprise
    "multi_cash": "Multi-caisses",
    "advanced_roles": "Gestion avancée des rôles et permissions",
    "multi_establishments": "Gestion multi-établissements",
    "consolidated_reports": "Consolidation des rapports",
    "activity_log": "Journal des activités",
    "strategic_dashboard": "Tableau de bord stratégique",
    "priority_support": "Assistance prioritaire",
}

PLAN_CATALOG = [
    {"name": "Starter", "price_fcfa": 2000, "max_users": 1,
     "description": "Pour les petits bars et débits de boissons", "features": STARTER},
    {"name": "Business", "price_fcfa": 5000, "max_users": 3,
     "description": "Pour les bars en croissance", "features": BUSINESS},
    {"name": "Premium", "price_fcfa": 10000, "max_users": 10,
     "description": "Pour les bars et snacks professionnels", "features": PREMIUM},
    {"name": "Enterprise", "price_fcfa": 20000, "max_users": UNLIMITED,
     "description": "Pour les grands établissements", "features": ENTERPRISE},
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