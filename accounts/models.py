from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.text import slugify


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', User.Role.SUPERADMIN)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPERADMIN = 'SUPERADMIN', 'Platform Administrator'
        BUSINESS_USER = 'BUSINESS_USER', 'Business Customer'

    username = None
    email = models.EmailField('Email Address', unique=True)
    phone_number = models.CharField(max_length=25, blank=True, null=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.BUSINESS_USER)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    objects = UserManager()

    @property
    def is_superadmin(self):
        return self.role == self.Role.SUPERADMIN or self.is_superuser

    @property
    def is_business_user(self):
        return self.role == self.Role.BUSINESS_USER

    def __str__(self):
        return f"{self.email} ({self.get_full_name() or 'User'})"


class Business(models.Model):
    class Category(models.TextChoices):
        GYM = 'GYM', 'Gym & Fitness Center'
        SCHOOL = 'SCHOOL', 'School & Education'
        CHURCH = 'CHURCH', 'Church & Religious Org'
        RETAIL = 'RETAIL', 'Shop & Retail Business'
        HEALTHCARE = 'HEALTHCARE', 'Clinic & Healthcare'
        SMB = 'SMB', 'Small/Medium Business'
        OTHER = 'OTHER', 'Other Organization'

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        PENDING_REVIEW = 'PENDING_REVIEW', 'Pending Review'
        DEACTIVATED = 'DEACTIVATED', 'Deactivated'

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    category = models.CharField(max_length=30, choices=Category.choices, default=Category.SMB)
    country = models.CharField(max_length=2, default='GH')
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=30)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    credit_balance = models.IntegerField(default=0, help_text="Cached balance verified against CreditLedgerEntry")
    preferred_sender_id = models.CharField(max_length=11, blank=True, help_text="Max 11 alphanumeric characters")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Businesses'
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or 'business'
            slug = base_slug
            counter = 1
            while Business.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} [{self.get_status_display()}]"


class BusinessMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = 'OWNER', 'Owner'
        ADMIN = 'ADMIN', 'Admin'
        MEMBER = 'MEMBER', 'Member'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memberships')
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.OWNER)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'business')
        verbose_name = 'Business Membership'

    def __str__(self):
        return f"{self.user.email} in {self.business.name} ({self.role})"


class AuditLog(models.Model):
    business = models.ForeignKey(Business, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_actions')
    action = models.CharField(max_length=100)
    description = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.action} - {self.description[:50]}"
