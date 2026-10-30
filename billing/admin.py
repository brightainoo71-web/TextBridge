from django.contrib import admin
from .models import SMSPackage, Purchase, PaymentTransaction, CreditLedgerEntry


@admin.register(SMSPackage)
class SMSPackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'credits', 'price_ghs', 'price_per_credit_display', 'estimated_margin_display', 'is_active', 'is_promotional')
    list_filter = ('is_active', 'is_promotional')
    search_fields = ('name', 'description')
    list_editable = ('price_ghs', 'is_active')

    def price_per_credit_display(self, obj):
        return f"GH₵{obj.price_per_credit:.4f}"
    price_per_credit_display.short_description = "Per SMS"

    def estimated_margin_display(self, obj):
        return f"GH₵{obj.estimated_margin:.2f}"
    estimated_margin_display.short_description = "Est. Margin"


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('payment_reference', 'business', 'package', 'credits_granted', 'amount_paid', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('payment_reference', 'business__name')
    readonly_fields = ('created_at', 'completed_at')


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_reference', 'purchase', 'provider', 'provider_fee', 'status', 'created_at')
    list_filter = ('provider', 'status', 'created_at')
    search_fields = ('transaction_reference', 'purchase__payment_reference')
    readonly_fields = ('created_at',)


@admin.register(CreditLedgerEntry)
class CreditLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'business', 'entry_type', 'amount', 'balance_after', 'reference_id')
    list_filter = ('entry_type', 'created_at')
    search_fields = ('business__name', 'reference_id', 'description')
    readonly_fields = ('created_at',)
