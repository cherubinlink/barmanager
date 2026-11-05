from django.urls import path
from catalog import views


app_name = 'catalog'


urlpatterns = [

     path("product_list/", views.product_list, name="product_list"),
    path("ajouter/", views.product_add, name="product_add"),
    path("ajouter/<int:pk>/", views.product_add_existing, name="product_add_existing"),
    path("nouveau/", views.product_propose, name="product_propose"),
    path("api/produits/", views.api_products, name="api_products"),

    path("<int:pk>/", views.product_detail, name="product_detail"),
    path("<int:pk>/modifier/", views.product_edit, name="product_edit"),
    path("<int:pk>/activer/", views.product_toggle, name="product_toggle"),

    path("<int:pk>/conditionnements/ajouter/", views.packaging_add, name="packaging_add"),
    path("conditionnements/<int:pk>/", views.packaging_edit, name="packaging_edit"),
    path("conditionnements/<int:pk>/supprimer/", views.packaging_delete, name="packaging_delete"),

    path("<int:pk>/portions/ajouter/", views.serving_add, name="serving_add"),
    path("portions/<int:pk>/", views.serving_edit, name="serving_edit"),
    path("portions/<int:pk>/supprimer/", views.serving_delete, name="serving_delete"),
    
]
