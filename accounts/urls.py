from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('dashboard/', views.DashboardRedirectView.as_view(), name='dashboard_redirect'),
    path('onboarding/', views.OnboardingView.as_view(), name='onboarding'),
    path('profile/', views.BusinessProfileView.as_view(), name='profile'),
    path('developer-keys/', views.DeveloperApiKeysView.as_view(), name='developer_keys'),
    path('developer-keys/<int:pk>/revoke/', views.RevokeApiKeyView.as_view(), name='revoke_api_key'),
    path('suspended/', views.SuspendedNoticeView.as_view(), name='suspended_notice'),
]
