from django.urls import path
from . import views

app_name = 'analytics'

urlpatterns = [
    path('dashboard/', views.CustomerDashboardView.as_view(), name='customer_dashboard'),
    path('admin-dashboard/', views.AdminDashboardView.as_view(), name='admin_dashboard'),
    path('admin/businesses/', views.AdminBusinessListView.as_view(), name='admin_business_list'),
    path('admin/businesses/<int:pk>/action/', views.AdminBusinessActionView.as_view(), name='admin_business_action'),
    path('admin/audit-logs/', views.AdminAuditLogListView.as_view(), name='admin_audit_logs'),
    path('export/<str:report_type>/', views.ExportReportView.as_view(), name='export_report'),
]
