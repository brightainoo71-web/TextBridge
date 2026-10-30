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
    path('suspended/', views.SuspendedNoticeView.as_view(), name='suspended_notice'),
]
