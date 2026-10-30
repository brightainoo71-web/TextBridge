import logging
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_welcome_email(user, business):
    """
    Sends an onboarding welcome email to newly registered business owners.
    """
    platform_name = getattr(settings, 'PLATFORM_NAME', 'TextBridge')
    subject = f"Welcome to {platform_name} - Your Workspace is Ready!"
    message = f"""Hi {user.first_name or 'there'},

Welcome to {platform_name}!

Your dedicated business messaging workspace for '{business.name}' has been successfully created.

Here are a few quick tips to get started:
1. Complete your business profile and verify your default Sender ID ({business.preferred_sender_id or 'Custom'}).
2. Import your customer contacts via CSV or Excel (.xlsx).
3. Choose an SMS credit package and launch your first broadcast campaign.

Sign in anytime at: http://127.0.0.1:8000/auth/login/

Best regards,
The {platform_name} Team
"""
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send welcome email to {user.email}: {e}")
        return False


def send_purchase_receipt_email(purchase):
    """
    Sends an order confirmation receipt upon successful package purchase.
    """
    business = purchase.business
    platform_name = getattr(settings, 'PLATFORM_NAME', 'TextBridge')
    subject = f"Receipt: SMS Package Purchase - {purchase.payment_reference}"
    message = f"""Hello {business.name},

Thank you for your purchase on {platform_name}.

Your payment has been verified and your SMS credits have been credited to your live ledger:

- Package: {purchase.package.name if purchase.package else 'SMS Credits'}
- Credits Added: +{purchase.credits_granted:,} SMS Credits
- Total Paid: {getattr(settings, 'CURRENCY_SYMBOL', 'GH₵')}{purchase.amount_paid} ({purchase.currency})
- Reference: {purchase.payment_reference}
- Current Running Balance: {business.credit_balance} Credits

You can view your complete purchase history and running ledger in your dashboard:
http://127.0.0.1:8000/billing/purchases/

Thank you for partnering with us!

Best regards,
{platform_name} Team
"""
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[business.contact_email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send receipt email to {business.contact_email}: {e}")
        return False
