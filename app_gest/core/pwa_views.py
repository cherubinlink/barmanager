from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse

THEME_COLOR = "#E8991C"


def manifest(request):
    """Manifeste de l'application installable. Généré par Django pour suivre le nom du site et les URLs."""
    name = getattr(settings, "SITE_NAME", "BarManager")
    data = {
        "id": "/",
        "name": f"{name} :  barmanager",
        "short_name": name,
        "description": "Caisse, stock, achats, crédits, messagerie et statistiques pour votre bar.",
        "lang": "fr",
        "dir": "ltr",
        "start_url": f"{settings.LOGIN_REDIRECT_URL}?source=pwa",
        "scope": "/",
        "display": "standalone",
        "display_override": ["standalone", "minimal-ui"],
        "orientation": "any",
        "background_color": "#FFFFFF",
        "theme_color": THEME_COLOR,
        "categories": ["business", "productivity"],
        "icons": [
            {"src": static("pwa/icons/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": static("pwa/icons/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": static("pwa/icons/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Nouveau ticket", "short_name": "Ticket", "url": reverse("sales:ticket_create")},
            {"name": "Tickets du jour", "short_name": "Ventes", "url": reverse("sales:ticket_list")},
            {"name": "Stock", "short_name": "Stock", "url": reverse("inventory:stock_list")},
            {"name": "Messagerie", "short_name": "Chat", "url": reverse("chat:conversation_list")},
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json")


def service_worker(request):
    """Le service worker est servi à la racine du site pour contrôler toutes les pages (portée « / »)."""
    response = render(request, "pwa/sw.js", {
        "version": getattr(settings, "PWA_VERSION", "1"), "static_url": settings.STATIC_URL},
        content_type="application/javascript")
    response["Cache-Control"] = "no-cache"                  # le navigateur doit toujours revérifier la version
    response["Service-Worker-Allowed"] = "/"
    return response


def offline(request):
    return render(request, "pwa/offline.html")