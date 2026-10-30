from django.contrib import admin
from .models import SenderID, SMSCampaign, CampaignRecipient, SMSMessage, ProviderAccountConfiguration


@admin.register(SenderID)
class SenderIDAdmin(admin.ModelAdmin):
    list_display = ('sender_id', 'business', 'status', 'purpose', 'created_at', 'approved_at')
    list_filter = ('status', 'created_at')
    search_fields = ('sender_id', 'business__name', 'purpose')
    actions = ['approve_sender_ids', 'reject_sender_ids']

    @admin.action(description="Approve selected Sender IDs")
    def approve_sender_ids(self, request, queryset):
        from django.utils import timezone
        queryset.update(status=SenderID.Status.APPROVED, approved_at=timezone.now())

    @admin.action(description="Reject selected Sender IDs")
    def reject_sender_ids(self, request, queryset):
        queryset.update(status=SenderID.Status.REJECTED)


@admin.register(SMSCampaign)
class SMSCampaignAdmin(admin.ModelAdmin):
    list_display = ('title', 'business', 'sender_id', 'status', 'total_recipients', 'valid_recipients_count', 'actual_credits_used', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('title', 'business__name', 'sender_id')
    readonly_fields = ('created_at',)


@admin.register(CampaignRecipient)
class CampaignRecipientAdmin(admin.ModelAdmin):
    list_display = ('phone_number', 'campaign', 'status', 'segments_count', 'credits_used', 'updated_at')
    list_filter = ('status',)
    search_fields = ('phone_number', 'campaign__title')


@admin.register(SMSMessage)
class SMSMessageAdmin(admin.ModelAdmin):
    list_display = ('recipient_phone', 'business', 'sender_id', 'status', 'credits_used', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('recipient_phone', 'business__name', 'sender_id', 'provider_message_id')


@admin.register(ProviderAccountConfiguration)
class ProviderAccountConfigurationAdmin(admin.ModelAdmin):
    list_display = ('name', 'provider_type', 'is_active', 'last_balance_check', 'last_checked_at')
    list_filter = ('provider_type', 'is_active')
