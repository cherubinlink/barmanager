"""
URL configuration for apps_bar project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path,include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # instalation
    path("", include("core.pwa_urls", namespace="pwa")),

    # apps
    path('', include('pages.urls', namespace='pages')),
    path('', include('accounts.urls', namespace='accounts')),
    path('tableau-de-bord/', include('dashboard.urls', namespace='dashboard')),
    path('core/', include('core.urls', namespace='core')),
    path('tenants/', include('tenants.urls', namespace='tenants')),
    path('catalog/', include('catalog.urls', namespace='catalog')),
    path('stock/', include('purchasing.urls', namespace='purchasing')),
    path('inventory/', include('inventory.urls', namespace='inventory')),
    path('sales/', include('sales.urls', namespace='sales')),
    path('credits/', include('credits.urls', namespace='credits')),
    path('notifications/', include('notifications.urls', namespace='notifications')),
    path('chat/', include('chat.urls', namespace='chat')),
    path('analytics/', include('analytics.urls', namespace='analytics')),
    
]


if settings.DEBUG:
    urlpatterns +=static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
