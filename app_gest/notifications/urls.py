from django.urls import path
from notifications import views


app_name = 'notifications'


urlpatterns = [

     # centre de notifications
    path("", views.notification_list, name="list"),
    path("<int:pk>/ouvrir/", views.notification_open, name="open"),
    path("<int:pk>/lue/", views.notification_read, name="read"),
    path("<int:pk>/supprimer/", views.notification_delete, name="delete"),
    path("tout-lire/", views.mark_all_read, name="mark_all_read"),
    path("vider/", views.clear_read, name="clear_read"),
 
    # API pour la cloche
    path("api/resume/", views.api_summary, name="api_summary"),
    path("api/lues/", views.api_mark_read, name="api_mark_read"),
 
    # préférences
    path("preferences/", views.preferences, name="preferences"),
    path("silence/", views.mute, name="mute"),
    path("test/", views.send_test, name="send_test"),
 
    # Web Push
    path("push/config/", views.push_config, name="push_config"),
    path("push/abonner/", views.push_subscribe, name="push_subscribe"),
    path("push/desabonner/", views.push_unsubscribe, name="push_unsubscribe"),
    
]
