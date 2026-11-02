from django.conf import settings
from django.shortcuts import render

from tenants.models import TRIAL_DAYS, Plan

# Create your views here.




FEATURES = [
    {
        "icon": "🧾", "title": "Caisse en temps réel",
        "text": "La vendeuse crée la commande dès que le client s’installe, et l’équipe la voit instantanément.",
        "bullets": [
            "Noms automatiques ClientA1 à ClientA10, puis B1…, remis à zéro chaque jour",
            "Nom du client facultatif, modifiable à tout moment",
            "Ajout de bières, whiskies, vins ou jus pendant la consommation",
            "Paiement immédiat, après consommation ou en plusieurs fois",
            "Facture en attente jusqu’à ce que le client ait fini et payé, puis finalisation",
        ],
    },
    {
        "icon": "📦", "title": "Stock et inventaires",
        "text": "Le stock est toujours exact : il se déduit de chaque entrée, vente et perte enregistrée.",
        "bullets": [
            "Inventaires par jour, semaine, mois, trimestre et année",
            "Les ventes vident d’abord le reste de l’ancienne commande (méthode FIFO)",
            "Comptage physique avec calcul des écarts (manquant ou surplus)",
            "Alertes de stock bas et de rupture",
            "Vente à la bouteille, au verre ou à la mesure (vin, whisky)",
        ],
    },
    {
        "icon": "🚚", "title": "Commandes aux fournisseurs",
        "text": "Commandez au dépôt dans les unités habituelles et suivez chaque réception.",
        "bullets": [
            "Casiers (bières), palettes (jus), cartons (vins), packs de canettes",
            "Commande déjà payée ou à crédit, avec date d’échéance",
            "Réception partielle ou totale, prix d’achat conservé par lot",
            "Prix modifiables selon votre fournisseur",
        ],
    },
    {
        "icon": "💳", "title": "Gestion des crédits",
        "text": "Ne perdez plus d’argent dans les ardoises oubliées ni dans les dettes mal suivies.",
        "bullets": [
            "Crédits clients : plafond, paiements partiels, historique",
            "Dettes fournisseurs : échéances, paiements échelonnés",
            "Relances et alertes à l’approche des échéances",
        ],
    },
    {
        "icon": "🍾", "title": "Pertes et casse",
        "text": "Chaque bouteille cassée est déclarée et rattachée à la commande concernée.",
        "bullets": [
            "Déclaration par la vendeuse avec motif et photo possible",
            "Validation par le gérant",
            "Pertes prises en compte dans chaque inventaire et dans la marge réelle",
        ],
    },
    {
        "icon": "👥", "title": "Équipe et rôles",
        "text": "Le gérant ajoute ses collaborateurs et décide de ce que chacun peut faire.",
        "bullets": [
            "Rôles prêts à l’emploi : gérant, caissier, vendeuse, magasinier",
            "Rôles personnalisables avec permissions précises",
            "Historique des actions de chaque utilisateur",
        ],
    },
    {
        "icon": "💬", "title": "Messagerie et notifications",
        "text": "Toute l’équipe d’un même bar communique sans quitter l’application.",
        "bullets": [
            "Messages privés, groupes et canal d’équipe, en temps réel",
            "Partage d’un ticket ou d’un produit dans la discussion",
            "Alertes : nouvelle commande QR, stock bas, perte à valider, créance échue",
            "Choix des notifications par utilisateur",
        ],
    },
    {
        "icon": "📈", "title": "Statistiques et prévisions",
        "text": "Comprenez ce qui rapporte vraiment et préparez vos commandes.",
        "bullets": [
            "Produit le plus vendu par jour, semaine, mois, trimestre et année",
            "Chiffre d’affaires, marges et heures de pointe",
            "Prévision des ventes et date de rupture probable",
            "Stratégies de vente suggérées : mise en avant, promotion, réapprovisionnement",
        ],
    },
    {
        "icon": "📱", "title": "Commande par QR code",
        "text": "Le client scanne le QR code du bar et commande depuis son téléphone.",
        "bullets": [
            "Aucune application à installer, aucun compte obligatoire",
            "La commande arrive à la vendeuse, qui la valide",
            "Chaque bar a son code client unique, modifiable",
        ],
    },
    {
        "icon": "🍺", "title": "Catalogue de produits prêt à l’emploi",
        "text": "Bières, vins, whiskies et jus sont déjà dans le système.",
        "bullets": [
            "Vous fixez vos propres prix et dates",
            "Produit absent ? Ajoutez-le : il enrichit le catalogue commun",
            "Vos prix restent privés, chaque bar garde les siens",
        ],
    },
]

PROBLEMS = [
    "Des erreurs de caisse et des additions qu’on ne retrouve plus",
    "Des bouteilles cassées ou disparues sans trace",
    "Des crédits clients oubliés, des dettes fournisseurs mal suivies",
    "Un stock qu’on ne connaît vraiment qu’à la fin du mois",
]

STEPS = [
    ("Créez votre compte", f"Inscription en quelques minutes, {TRIAL_DAYS} jours d’essai gratuit sans engagement."),
    ("Configurez votre bar", "Choisissez vos produits, fixez vos prix, ajoutez vos fournisseurs et votre équipe."),
    ("Enregistrez vos arrivages", "Chaque commande reçue crée un lot de stock avec son prix d’achat."),
    ("Vendez au quotidien", "Tickets en temps réel, paiements, crédits, pertes : tout est tracé."),
    ("Clôturez et analysez", "Inventaire du jour, écarts, statistiques et conseils pour mieux vendre."),
]

ROLES = [
    ("Gérant", "Accès complet : prix, utilisateurs, rôles, inventaires, rapports, abonnement."),
    ("Caissier", "Encaissements, finalisation des factures, remises, suivi des crédits clients."),
    ("Vendeuse", "Création et modification des commandes, validation des commandes QR, déclaration des pertes."),
    ("Magasinier", "Réception des commandes fournisseurs, comptage du stock, déclaration des pertes."),
]

FAQ = [
    ("Que se passe-t-il à la fin des 30 jours d’essai ?",
     "Votre compte passe en lecture seule : vous gardez l’accès à toutes vos données. "
     "Il redevient complet dès que votre abonnement est réglé."),
    ("Comment payer l’abonnement ?",
     "Le paiement est manuel au départ (par exemple Mobile Money). Vous déclarez votre paiement, "
     "l’administrateur le valide, et votre abonnement est prolongé."),
    ("Qui fixe les tarifs ?",
     "L’administrateur de la plateforme. Les tarifs en vigueur sont affichés sur cette page."),
    ("Mes données sont-elles séparées de celles des autres bars ?",
     "Oui. Chaque bar dispose de son propre espace : stock, prix, clients et équipe lui sont propres."),
    ("Le client doit-il donner son nom ?",
     "Non. Le système attribue automatiquement ClientA1, ClientA2… ; le nom reste facultatif."),
    ("Puis-je utiliser l’application sur téléphone ?",
     "Oui, elle fonctionne dans le navigateur d’un téléphone, d’une tablette ou d’un ordinateur."),
    ("Que devient une bouteille cassée ?",
     "La vendeuse la déclare, le gérant la valide, et la perte est imputée à la commande concernée."),
]



def home(request):
    context = {
        "site_name": getattr(settings, "SITE_NAME", "BarManager"),
        "trial_days": TRIAL_DAYS,
        "plans": Plan.objects.filter(is_active=True),
        "features": FEATURES,
        "problems": PROBLEMS,
        "steps": STEPS,
        "roles": ROLES,
        "faq": FAQ,
        "login_url": settings.LOGIN_URL,
        "register_url": getattr(settings, "REGISTER_URL", "/inscription/"),
        "dashboard_url": getattr(settings, "LOGIN_REDIRECT_URL", "/"),
        "contact_phone": getattr(settings, "CONTACT_PHONE", ""),
        "contact_email": getattr(settings, "CONTACT_EMAIL", ""),
    }
    return render(request, "pages/home.html", context)
