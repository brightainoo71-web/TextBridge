from django.urls import path
from . import views

app_name = 'billing'

urlpatterns = [
    path('packages/', views.PackagesView.as_view(), name='packages'),
    path('checkout/<int:package_id>/', views.CheckoutInitiateView.as_view(), name='checkout_initiate'),
    path('sandbox-checkout/<str:reference>/', views.SandboxCheckoutView.as_view(), name='sandbox_checkout'),
    path('callback/', views.PaymentCallbackView.as_view(), name='payment_callback'),
    path('webhook/paystack/', views.PaystackWebhookView.as_view(), name='paystack_webhook'),
    path('purchases/', views.PurchaseHistoryView.as_view(), name='purchase_history'),
    path('ledger/', views.CreditLedgerView.as_view(), name='credit_ledger'),
]
