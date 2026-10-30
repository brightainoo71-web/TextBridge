from django.contrib import admin
from .models import Contact, ContactGroup, ContactGroupMembership, SuppressionRecord, ConsentRecord


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone_number', 'email', 'business', 'is_subscribed', 'created_at')
    list_filter = ('is_subscribed', 'created_at')
    search_fields = ('name', 'phone_number', 'email', 'business__name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ContactGroup)
class ContactGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'business', 'member_count', 'created_at')
    search_fields = ('name', 'business__name')
    readonly_fields = ('created_at',)


@admin.register(SuppressionRecord)
class SuppressionRecordAdmin(admin.ModelAdmin):
    list_display = ('phone_number', 'business', 'reason', 'created_at')
    list_filter = ('reason', 'created_at')
    search_fields = ('phone_number', 'business__name')


@admin.register(ConsentRecord)
class ConsentRecordAdmin(admin.ModelAdmin):
    list_display = ('contact', 'lawful_basis', 'captured_at')
    list_filter = ('lawful_basis', 'captured_at')
    search_fields = ('contact__phone_number', 'contact__name')
    readonly_fields = ('captured_at',)
