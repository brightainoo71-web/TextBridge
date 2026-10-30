from django.db import models
from django.conf import settings
from decimal import Decimal
from accounts.models import Business, User


class SMSPackage(models.Model):
    name = models.CharField(max_length=100)
    credits = models.PositiveIntegerField(help_text="Number of SMS credits included")
    price_ghs = models.DecimalField(max_digits=10, decimal_places=2, help_text="Retail price in GHS")
    estimated_provider_cost_ghs = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Platform provider expense assumption for margin calculations"
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_promotional = models.BooleanField(default=False)
    promo_price_ghs = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['price_ghs']
        verbose_name = 'SMS Package'

    @property
    def effective_price(self):
        if self.is_promotional and self.promo_price_ghs is not None:
            return self.promo_price_ghs
        return self.price_ghs

    @property
    def price_per_credit(self):
        if self.credits > 0:
            return round(self.effective_price / self.credits, 4)
        return Decimal('0.0000')

    @property
    def estimated_margin(self):
        return self.effective_price - self.estimated_provider_cost_ghs

    def __str__(self):
        return f"{self.name} - {self.credits:,} SMS ({getattr(settings, 'CURRENCY_SYMBOL', 'GH₵')}{self.effective_price})"


class Purchase(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Payment'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        REFUNDED = 'REFUNDED', 'Refunded'

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='purchases')
    package = models.ForeignKey(SMSPackage, on_delete=models.SET_NULL, null=True, blank=True)
    credits_granted = models.PositiveIntegerField()
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default='GHS')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    payment_reference = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Purchase #{self.id} - {self.business.name} ({self.credits_granted:,} credits, {self.status})"


class PaymentTransaction(models.Model):
    class Provider(models.TextChoices):
        PAYSTACK = 'PAYSTACK', 'Paystack'
        SANDBOX = 'SANDBOX', 'Dev Sandbox Simulator'
        MANUAL = 'MANUAL', 'Admin Manual Credit'

    class Status(models.TextChoices):
        INITIALIZED = 'INITIALIZED', 'Initialized'
        SUCCESS = 'SUCCESS', 'Success'
        FAILED = 'FAILED', 'Failed'

    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='transactions')
    provider = models.CharField(max_length=30, choices=Provider.choices, default=Provider.PAYSTACK)
    transaction_reference = models.CharField(max_length=120, unique=True)
    provider_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    raw_response = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INITIALIZED)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.provider} Tx {self.transaction_reference} - {self.status}"


class CreditLedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        PURCHASE_CREDIT = 'PURCHASE_CREDIT', 'Package Purchase Credit'
        CAMPAIGN_RESERVATION = 'CAMPAIGN_RESERVATION', 'Campaign Usage Reservation'
        CAMPAIGN_USAGE_DEBIT = 'CAMPAIGN_USAGE_DEBIT', 'Actual Campaign Dispatch Debit'
        RESERVATION_RELEASE = 'RESERVATION_RELEASE', 'Unused Reservation Release'
        REFUND = 'REFUND', 'Purchase Refund Reversal'
        ADMIN_ADJUSTMENT = 'ADMIN_ADJUSTMENT', 'Platform Admin Adjustment'
        REVERSAL = 'REVERSAL', 'Correction Reversal'

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='ledger_entries')
    entry_type = models.CharField(max_length=30, choices=EntryType.choices)
    amount = models.IntegerField(help_text="Positive for additions, negative for deductions")
    balance_after = models.IntegerField(help_text="Exact verified balance after this transaction")
    purchase = models.ForeignKey(Purchase, on_delete=models.SET_NULL, null=True, blank=True, related_name='ledger_entries')
    campaign_id = models.IntegerField(null=True, blank=True, help_text="Associated SMSCampaign ID if applicable")
    description = models.CharField(max_length=255)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reference_id = models.CharField(max_length=120, unique=True, help_text="Idempotency key preventing duplicate executions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['business', '-created_at']),
            models.Index(fields=['reference_id']),
        ]

    def __str__(self):
        sign = '+' if self.amount >= 0 else ''
        return f"{self.business.name} | {self.entry_type} | {sign}{self.amount} -> Bal: {self.balance_after}"
