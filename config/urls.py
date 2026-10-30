from django.contrib import admin
from django.urls import path, include
from accounts.views import LandingPageView
from messaging.api import SendSMSApiView, BalanceApiView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', LandingPageView.as_view(), name='landing'),
    path('auth/', include('accounts.urls', namespace='accounts')),
    path('contacts/', include('contacts.urls', namespace='contacts')),
    path('billing/', include('billing.urls', namespace='billing')),
    path('messaging/', include('messaging.urls', namespace='messaging')),
    path('analytics/', include('analytics.urls', namespace='analytics')),

    # Developer REST API (v1)
    path('api/v1/sms/send', SendSMSApiView.as_view(), name='api_sms_send'),
    path('api/v1/balance', BalanceApiView.as_view(), name='api_balance'),
]
