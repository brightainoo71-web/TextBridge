from django.db import models
from accounts.models import Business
from contacts.models import Contact, ContactGroup


class SenderID(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Platform Approval'
        APPROVED = 'APPROVED', 'Approved & Active'
        REJECTED = 'REJECTED', 'Rejected'

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='sender_ids',
        help_text="Tenant business that owns this Sender ID (null if platform-wide system default)"
    )
    sender_id = models.CharField(
        max_length=11,
        help_text="Exact alphanumeric sender ID (max 11 characters, no special symbols)"
    )
    purpose = models.CharField(max_length=255, help_text="e.g., Gym schedule updates, School announcements")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.APPROVED)
    is_system_default = models.BooleanField(
        default=False,
        help_text="Designates this as a platform-wide default accessible to all tenant businesses"
    )
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['business', 'sender_id'],
                condition=models.Q(business__isnull=False),
                name='unique_business_sender_id'
            ),
            models.UniqueConstraint(
                fields=['sender_id'],
                condition=models.Q(is_system_default=True),
                name='unique_system_sender_id'
            ),
        ]

    def __str__(self):
        owner = self.business.name if self.business else "Platform Default"
        return f"{self.sender_id} ({owner}) [{self.status}]"


class SMSCampaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        QUEUED = 'QUEUED', 'Queued'
        PROCESSING = 'PROCESSING', 'Processing'
        COMPLETED = 'COMPLETED', 'Completed'
        PARTIAL_FAILURE = 'PARTIAL_FAILURE', 'Partial Failure'
        FAILED = 'FAILED', 'Failed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='campaigns')
    title = models.CharField(max_length=150)
    sender_id = models.CharField(max_length=11)
    message_template = models.TextField(help_text="Supports personalization placeholders such as {{name}}")
    target_group = models.ForeignKey(
        ContactGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='campaigns'
    )
    is_scheduled = models.BooleanField(default=False)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    total_recipients = models.PositiveIntegerField(default=0)
    valid_recipients_count = models.PositiveIntegerField(default=0)
    suppressed_recipients_count = models.PositiveIntegerField(default=0)
    estimated_credits = models.PositiveIntegerField(default=0)
    actual_credits_used = models.PositiveIntegerField(default=0)

    provider_reference = models.CharField(max_length=120, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Campaign: {self.title} ({self.business.name}) [{self.status}]"


class CampaignRecipient(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'QUEUED', 'Queued'
        SUBMITTED = 'SUBMITTED', 'Submitted to Gateway'
        ACCEPTED = 'ACCEPTED', 'Accepted by Gateway'
        DELIVERED = 'DELIVERED', 'Delivered'
        FAILED = 'FAILED', 'Failed'
        REJECTED = 'REJECTED', 'Rejected'
        UNKNOWN = 'UNKNOWN', 'Unknown'

    campaign = models.ForeignKey(SMSCampaign, on_delete=models.CASCADE, related_name='recipients')
    contact = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True)
    phone_number = models.CharField(max_length=25)
    recipient_name = models.CharField(max_length=150, blank=True)
    rendered_message = models.TextField()
    segments_count = models.PositiveSmallIntegerField(default=1)
    credits_used = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    provider_message_id = models.CharField(max_length=120, blank=True)
    error_message = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['campaign', 'status']),
            models.Index(fields=['phone_number']),
        ]

    def __str__(self):
        return f"{self.phone_number} - {self.status}"


class SMSMessage(models.Model):
    """
    Direct single/test messages.
    """
    class Status(models.TextChoices):
        QUEUED = 'QUEUED', 'Queued'
        DELIVERED = 'DELIVERED', 'Delivered'
        FAILED = 'FAILED', 'Failed'

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='direct_messages')
    recipient_phone = models.CharField(max_length=25)
    sender_id = models.CharField(max_length=11)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    provider_message_id = models.CharField(max_length=120, blank=True)
    credits_used = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"SMS to {self.recipient_phone} [{self.status}]"


class ProviderAccountConfiguration(models.Model):
    class ProviderType(models.TextChoices):
        MNOTIFY = 'MNOTIFY', 'mNotify SMS API'
        MOCK = 'MOCK', 'Mock Simulator'

    name = models.CharField(max_length=100)
    provider_type = models.CharField(max_length=20, choices=ProviderType.choices, default=ProviderType.MOCK)
    api_key = models.CharField(max_length=255, blank=True)
    base_url = models.CharField(max_length=255, default='https://api.mnotify.com/api')
    is_active = models.BooleanField(default=True)
    last_balance_check = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        active_tag = "ACTIVE" if self.is_active else "INACTIVE"
        return f"{self.name} ({self.provider_type}) - [{active_tag}]"
