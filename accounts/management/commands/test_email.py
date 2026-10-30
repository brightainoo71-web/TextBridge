from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings


class Command(BaseCommand):
    help = 'Tests transactional email delivery via Resend / SMTP'

    def add_arguments(self, parser):
        parser.add_argument('--to', type=str, required=True, help='Recipient email address for test')

    def handle(self, *args, **options):
        recipient = options['to']
        self.stdout.write(f"Testing email delivery via {settings.EMAIL_BACKEND}...")
        self.stdout.write(f"From: {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write(f"To: {recipient}")

        subject = f"Test Email from {getattr(settings, 'PLATFORM_NAME', 'BrightSMS')} via Resend"
        body = f"""Hello,

This is a test message confirming that your transactional email integration on BrightSMS is functioning correctly with Resend.

- Platform: {getattr(settings, 'PLATFORM_NAME', 'BrightSMS')}
- Email Service: Resend (smtp.resend.com)
- Timestamp: Verified live

If you received this email, your onboarding welcome emails and purchase receipts will be delivered smoothly!

Best regards,
The Engineering Team
"""
        try:
            sent = send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False
            )
            if sent:
                self.stdout.write(self.style.SUCCESS(f"Email successfully delivered to {recipient}!"))
            else:
                self.stdout.write(self.style.WARNING("Email call completed but returned 0 sent messages."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to send email: {str(e)}"))
