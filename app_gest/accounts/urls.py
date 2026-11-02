from django.urls import path
from django.contrib.auth.views import LoginView, LogoutView
from accounts import views


app_name = 'accounts'



urlpatterns = [

    path("inscription/", views.register, name="register"),
    path("connexion/", LoginView.as_view(template_name="accounts/auth_form.html", redirect_authenticated_user=True,
        extra_context={"title": "Connexion", "submit": "Se connecter","alt_url": "accounts:register", "alt_text": "Créer un compte"},
    ), name="login"),
    path("deconnexion/", LogoutView.as_view(), name="logout"),
    path("mes-bars/", views.select_bar, name="select_bar"),
    path("nouveau-bar/", views.new_bar, name="new_bar"),
    path("aucun-bar/", views.no_bar, name="no_bar"),
    
]
