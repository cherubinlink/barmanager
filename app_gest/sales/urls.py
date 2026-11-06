from django.urls import path
from sales import views


app_name = 'sales'


urlpatterns = [

      # tickets
    path("", views.ticket_list, name="ticket_list"),
    path("nouveau/", views.ticket_create, name="ticket_create"),
    path("tickets/<int:pk>/", views.ticket_detail, name="ticket_detail"),
    path("tickets/<int:pk>/ligne/", views.line_add, name="line_add"),
    path("tickets/<int:pk>/ligne/<int:line_pk>/annuler/", views.line_void, name="line_void"),
    path("tickets/<int:pk>/remise/", views.ticket_discount, name="ticket_discount"),
    path("tickets/<int:pk>/facture/", views.ticket_invoice, name="ticket_invoice"),
    path("tickets/<int:pk>/paiement/", views.payment_add, name="payment_add"),
    path("tickets/<int:pk>/remboursement/", views.payment_refund, name="payment_refund"),
    path("tickets/<int:pk>/finaliser/", views.ticket_finalize, name="ticket_finalize"),
    path("tickets/<int:pk>/annuler/", views.ticket_cancel, name="ticket_cancel"),
 
    # commandes QR
    path("qr/<int:pk>/valider/", views.qr_validate, name="qr_validate"),
    path("qr/<int:pk>/rejeter/", views.qr_reject, name="qr_reject"),
 
    # clients
    path("clients/", views.customer_list, name="customer_list"),
    path("clients/nouveau/", views.customer_create, name="customer_create"),
    path("clients/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("clients/<int:pk>/modifier/", views.customer_edit, name="customer_edit"),
 
    # rapport
    path("rapport/", views.sales_report_view, name="report"),
    
]
