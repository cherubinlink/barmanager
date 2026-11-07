from django.urls import path
from analytics import views


app_name = 'analytics'



urlpatterns = [

     path("", views.dashboard, name="dashboard"),
    path("actualiser/", views.stats_refresh, name="stats_refresh"),
 
    # journées
    path("journees/", views.summary_list, name="summary_list"),
    path("journees/export/", views.export_summaries, name="export_summaries"),
    path("journees/<int:pk>/", views.summary_detail, name="summary_detail"),
 
    # produits
    path("produits/", views.product_stats, name="product_stats"),
    path("produits/<int:pk>/", views.product_analysis, name="product_analysis"),
 
    # prévisions
    path("previsions/", views.forecast_list, name="forecast_list"),
    path("previsions/recalculer/", views.forecast_refresh, name="forecast_refresh"),
 
    # recommandations
    path("recommandations/", views.recommendation_list, name="recommendation_list"),
    path("recommandations/analyser/", views.recommendation_refresh, name="recommendation_refresh"),
    path("recommandations/<int:pk>/statut/", views.recommendation_status, name="recommendation_status"),
 
    # API pour les graphiques
    path("api/serie/", views.api_series, name="api_series"),
    path("api/heures/", views.api_hours, name="api_hours"),
    path("api/produits/", views.api_top_products, name="api_top_products"),
    
]
