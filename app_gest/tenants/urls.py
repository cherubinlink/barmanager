from django.urls import path
from tenants import views


app_name = 'tenants'


urlpatterns = [
    path("reglages/", views.bar_settings, name="settings"),
    path("qr/", views.bar_qr, name="qr"),
    path("qr.png", views.bar_qr_png, name="qr_png"),
    path("abonnement/", views.subscription, name="subscription"),
    path("b/", views.enter_code, name="enter_code"),
    path("b/<uuid:public_id>/", views.public_entry, name="public_entry"),
    path("b/<uuid:public_id>/commander/", views.public_order, name="public_order"),
]
