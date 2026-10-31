from django.urls import path
from . import views

app_name = 'contacts'

urlpatterns = [
    path('', views.ContactListView.as_view(), name='contact_list'),
    path('new/', views.ContactCreateView.as_view(), name='contact_create'),
    path('<int:pk>/edit/', views.ContactUpdateView.as_view(), name='contact_update'),
    path('<int:pk>/delete/', views.ContactDeleteView.as_view(), name='contact_delete'),
    path('groups/', views.ContactGroupListView.as_view(), name='group_list'),
    path('groups/<int:pk>/delete/', views.ContactGroupDeleteView.as_view(), name='group_delete'),
    path('import/', views.ContactImportView.as_view(), name='contact_import'),
    path('template/', views.DownloadSampleTemplateView.as_view(), name='download_template'),
    path('suppression/', views.SuppressionListView.as_view(), name='suppression_list'),
    path('suppression/<int:pk>/delete/', views.SuppressionDeleteView.as_view(), name='suppression_delete'),
    path('export/', views.ContactExportView.as_view(), name='contact_export'),
    path('birthdays/', views.BirthdayAutomationView.as_view(), name='birthday_automation'),
    path('birthdays/test/', views.BirthdayTestDispatchView.as_view(), name='birthday_test_dispatch'),
]
