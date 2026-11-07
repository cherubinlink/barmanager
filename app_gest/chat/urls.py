from django.urls import path
from chat import views

app_name = 'chat'


urlpatterns = [

     # pages
    path("", views.conversation_list, name="conversation_list"),
    path("membres/", views.member_list, name="member_list"),
    path("direct/", views.direct_start, name="direct_start"),
    path("groupes/nouveau/", views.group_create, name="group_create"),
    path("<int:pk>/", views.conversation_detail, name="conversation_detail"),
    path("<int:pk>/renommer/", views.group_rename, name="group_rename"),
    path("<int:pk>/participants/ajouter/", views.participants_add, name="participants_add"),
    path("<int:pk>/participants/<int:user_id>/retirer/", views.participant_remove, name="participant_remove"),
    path("<int:pk>/quitter/", views.conversation_leave, name="conversation_leave"),
    path("<int:pk>/sourdine/", views.conversation_mute, name="conversation_mute"),
    path("<int:pk>/archiver/", views.conversation_archive, name="conversation_archive"),
 
    # API JSON
    path("api/non-lus/", views.api_unread, name="api_unread"),
    path("api/presence/", views.api_presence, name="api_presence"),
    path("<int:pk>/api/messages/", views.api_messages, name="api_messages"),
    path("<int:pk>/api/envoyer/", views.api_send, name="api_send"),
    path("<int:pk>/api/lu/", views.api_read, name="api_read"),
    path("<int:pk>/api/recherche/", views.api_search, name="api_search"),
    path("messages/<int:msg_pk>/api/modifier/", views.api_edit, name="api_edit"),
    path("messages/<int:msg_pk>/api/supprimer/", views.api_delete, name="api_delete"),
    
]
