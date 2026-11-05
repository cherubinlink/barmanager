from django.urls import path
from purchasing import views


app_name = 'purchasing'


urlpatterns = [

     # commandes
    path("", views.order_list, name="order_list"),
    path("nouvelle/", views.order_create, name="order_create"),
    path("<int:pk>/", views.order_detail, name="order_detail"),
    path("<int:pk>/modifier/", views.order_edit, name="order_edit"),
    path("<int:pk>/envoyer/", views.order_send, name="order_send"),
    path("<int:pk>/annuler/", views.order_cancel, name="order_cancel"),
    path("<int:pk>/cloturer/", views.order_close, name="order_close"),
    path("<int:pk>/recevoir/", views.order_receive, name="order_receive"),
    path("<int:pk>/lignes/ajouter/", views.line_add, name="line_add"),
    path("lignes/<int:pk>/", views.line_edit, name="line_edit"),
    path("lignes/<int:pk>/supprimer/", views.line_delete, name="line_delete"),
    path("<int:pk>/paiements/ajouter/", views.payment_add, name="payment_add"),
    path("paiements/<int:pk>/supprimer/", views.payment_delete, name="payment_delete"),

    # fournisseurs
    path("fournisseurs/", views.supplier_list, name="supplier_list"),
    path("fournisseurs/nouveau/", views.supplier_add, name="supplier_add"),
    path("fournisseurs/<int:pk>/", views.supplier_detail, name="supplier_detail"),
    path("fournisseurs/<int:pk>/modifier/", views.supplier_edit, name="supplier_edit"),
    path("fournisseurs/<int:pk>/activer/", views.supplier_toggle, name="supplier_toggle"),
    
]
