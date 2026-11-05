from django.urls import path
from inventory import views


app_name = 'inventory'


urlpatterns = [

     # stock
    path("", views.stock_list, name="stock_list"),
    path("produits/<int:pk>/", views.stock_product, name="stock_product"),
    path("mouvements/", views.movement_list, name="movement_list"),
    path("stock-initial/", views.opening_stock, name="opening_stock"),
    path("ajustement/", views.adjust_stock, name="adjust_stock"),

    # pertes
    path("pertes/", views.loss_list, name="loss_list"),
    path("pertes/declarer/", views.loss_create, name="loss_create"),
    path("pertes/<int:pk>/valider/", views.loss_approve, name="loss_approve"),
    path("pertes/<int:pk>/rejeter/", views.loss_reject, name="loss_reject"),

    # inventaires physiques
    path("inventaires/", views.count_list, name="count_list"),
    path("inventaires/nouveau/", views.count_create, name="count_create"),
    path("inventaires/<int:pk>/", views.count_detail, name="count_detail"),
    path("inventaires/<int:pk>/valider/", views.count_validate, name="count_validate"),
    path("inventaires/<int:pk>/supprimer/", views.count_delete, name="count_delete"),

    # rapport par période et clôtures
    path("rapport/", views.inventory_report, name="report"),
    path("clotures/", views.closing_list, name="closing_list"),
    path("clotures/cloturer/", views.closing_close, name="closing_close"),
    path("clotures/<int:pk>/", views.closing_detail, name="closing_detail"),
    
]
