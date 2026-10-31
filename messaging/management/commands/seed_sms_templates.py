from django.core.management.base import BaseCommand
from messaging.models import SMSTemplate


class Command(BaseCommand):
    help = "Seeds default Ghanaian business SMS templates into the platform preset library."

    def handle(self, *args, **options):
        presets = [
            {
                "title": "Welcome & Onboarding Greeting",
                "category": SMSTemplate.Category.ONBOARDING,
                "content": "Welcome {{first_name}}! We are delighted to have you with us. If you have any questions, feel free to reply or call us directly. Welcome aboard!",
                "is_system_preset": True,
            },
            {
                "title": "Payment & Receipt Confirmation",
                "category": SMSTemplate.Category.BILLING,
                "content": "Hi {{name}}, we have received your payment of GHS {{amount}} (Ref: {{ref}}). Your account has been credited. Thank you for choosing us!",
                "is_system_preset": True,
            },
            {
                "title": "Appointment / Class Reminder",
                "category": SMSTemplate.Category.REMINDERS,
                "content": "Hi {{first_name}}, this is a friendly reminder for your upcoming appointment/class scheduled for {{date}} at {{time}}. See you then!",
                "is_system_preset": True,
            },
            {
                "title": "Flash Sale & Promotional Discount",
                "category": SMSTemplate.Category.MARKETING,
                "content": "Flash Promo! Enjoy up to 30% OFF this weekend only. Visit us today or order online before stocks run out. Terms apply.",
                "is_system_preset": True,
            },
            {
                "title": "Order Ready / Delivery Dispatch",
                "category": SMSTemplate.Category.ALERTS,
                "content": "Hello {{first_name}}, your order #{{order_id}} has been dispatched and is on its way to you. Our rider will contact you upon arrival.",
                "is_system_preset": True,
            },
            {
                "title": "General Urgent Service Notice",
                "category": SMSTemplate.Category.GENERAL,
                "content": "Notice to our valued clients: {{announcement}}. For urgent inquiries, please contact our support desk directly. Thank you for your understanding.",
                "is_system_preset": True,
            },
        ]

        created_count = 0
        for p in presets:
            obj, created = SMSTemplate.objects.get_or_create(
                business=None,
                title=p["title"],
                defaults=p
            )
            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully seeded {created_count} default SMS templates."))
