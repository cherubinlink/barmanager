from django.urls import path, reverse_lazy
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from accounts import views


app_name = 'accounts'



urlpatterns = [

    path("inscription/", views.register, name="register"),
    path("connexion/", views.StaffLoginView.as_view(), name="login"),
    path("deconnexion/", LogoutView.as_view(), name="logout"),
    path("mes-bars/", views.select_bar, name="select_bar"),
    path("nouveau-bar/", views.new_bar, name="new_bar"),
    path("aucun-bar/", views.no_bar, name="no_bar"),

    path("equipe/", views.team, name="team"),
    path("equipe/ajouter/", views.member_add, name="member_add"),
    path("equipe/<int:pk>/", views.member_edit, name="member_edit"),
    path("roles/", views.roles, name="roles"),
    path("roles/nouveau/", views.role_add, name="role_add"),
    path("roles/<int:pk>/", views.role_edit, name="role_edit"),
    path("roles/<int:pk>/supprimer/", views.role_delete, name="role_delete"),

    path("profil/", views.profile, name="profile"),
    path("mot-de-passe/", PasswordChangeView.as_view(
        template_name="accounts/auth_form.html", success_url=reverse_lazy("accounts:profile"),
        extra_context={"title": "Changer mon mot de passe", "submit": "Enregistrer",
                       "alt_url": "accounts:profile", "alt_text": "Retour au profil"},
    ), name="password_change"),
    
]
