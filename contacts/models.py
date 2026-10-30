from django.db import models
from accounts.models import Business


class ContactGroup(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='contact_groups')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('business', 'name')
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.business.name})"

    @property
    def member_count(self):
        return self.contact_memberships.count()


class Contact(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='contacts')
    name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=25, help_text="Normalized format: 233XXXXXXXXX")
    email = models.EmailField(blank=True, null=True)
    custom_attributes = models.JSONField(default=dict, blank=True)
    is_subscribed = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('business', 'phone_number')
        ordering = ['name', 'phone_number']

    def __str__(self):
        return f"{self.name} ({self.phone_number})"


class ContactGroupMembership(models.Model):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='group_memberships')
    group = models.ForeignKey(ContactGroup, on_delete=models.CASCADE, related_name='contact_memberships')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('contact', 'group')

    def __str__(self):
        return f"{self.contact.name} in {self.group.name}"


class SuppressionRecord(models.Model):
    class Reason(models.TextChoices):
        OPT_OUT = 'OPT_OUT', 'User Opted Out / Unsubscribed'
        ADMIN_BLOCKED = 'ADMIN_BLOCKED', 'Administrator Blocked'
        BOUNCE = 'BOUNCE', 'Repeatedly Bounced / Invalid'
        COMPLAINT = 'COMPLAINT', 'Spam Complaint'

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='suppressions',
        help_text="If null, suppressed globally across platform"
    )
    phone_number = models.CharField(max_length=25)
    reason = models.CharField(max_length=30, choices=Reason.choices, default=Reason.OPT_OUT)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Suppressed: {self.phone_number} ({self.reason})"


class ConsentRecord(models.Model):
    class LawfulBasis(models.TextChoices):
        CONSENT = 'CONSENT', 'Direct Explicit Consent'
        CONTRACT = 'CONTRACT', 'Performance of a Contract'
        LEGITIMATE_INTEREST = 'LEGITIMATE_INTEREST', 'Legitimate Business Interest'
        LEGAL_OBLIGATION = 'LEGAL_OBLIGATION', 'Legal Obligation'

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='consent_records')
    lawful_basis = models.CharField(max_length=40, choices=LawfulBasis.choices, default=LawfulBasis.CONSENT)
    notes = models.TextField(blank=True)
    captured_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Consent for {self.contact.phone_number}: {self.lawful_basis}"
