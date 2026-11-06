from django.urls import path
from credits import views

app_name ='credits'


urlpatterns = [

    path("", views.credit_list, name="credit_list"),
    path("nouvelle/", views.credit_create, name="credit_create"),
    path("<int:pk>/", views.credit_detail, name="credit_detail"),
    path("<int:pk>/reglement/", views.payment_add, name="payment_add"),
    path("<int:pk>/echeance/", views.due_date_update, name="due_date_update"),
    path("<int:pk>/perte/", views.credit_write_off, name="credit_write_off"),
    path("<int:pk>/relance/", views.reminder_add, name="reminder_add"),
    
]
