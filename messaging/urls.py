from django.urls import path
from . import views

app_name = 'messaging'

urlpatterns = [
    path('campaigns/', views.CampaignListView.as_view(), name='campaign_list'),
    path('campaigns/new/', views.CampaignCreateView.as_view(), name='campaign_create'),
    path('campaigns/<int:pk>/', views.CampaignDetailView.as_view(), name='campaign_detail'),
    path('campaigns/<int:pk>/cancel/', views.CampaignCancelView.as_view(), name='campaign_cancel'),
    path('send-single/', views.SingleTestMessageView.as_view(), name='single_message'),
    path('sender-ids/', views.SenderIDListView.as_view(), name='sender_ids'),
    path('api/calculate-segments/', views.CalculateSegmentsApiView.as_view(), name='api_calculate_segments'),
    path('webhook/mnotify/', views.MNotifyDlrWebhookView.as_view(), name='mnotify_dlr_webhook'),
]
