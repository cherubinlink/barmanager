from django.urls import path

from core import pwa_views as views

app_name = "pwa"

urlpatterns = [
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("hors-ligne/", views.offline, name="offline"),
]