from django.core.management.base import BaseCommand
from django.utils import timezone
from messaging.providers import get_sms_provider
from messaging.models import SenderID
from accounts.models import Business


class Command(BaseCommand):
    help = 'Synchronizes approved Sender IDs from mNotify gateway account into the database'

    def handle(self, *args, **options):
        provider = get_sms_provider()
        if not hasattr(provider, 'get_approved_sender_ids'):
            self.stdout.write(self.style.WARNING("Active provider does not support sender ID synchronization."))
            return

        sender_ids = provider.get_approved_sender_ids()
        if not sender_ids:
            self.stdout.write(self.style.WARNING("No sender IDs returned from gateway."))
            return

        businesses = Business.objects.all()
        synced_count = 0

        for item in sender_ids:
            s_name = item.get('sender_name')
            s_purpose = item.get('purpose', 'Imported from mNotify')
            s_status = item.get('status', 'approved')

            if not s_name:
                continue

            status_enum = SenderID.Status.APPROVED if s_status == 'approved' else SenderID.Status.PENDING

            for biz in businesses:
                sid, created = SenderID.objects.get_or_create(
                    business=biz,
                    sender_id=s_name,
                    defaults={
                        'purpose': s_purpose,
                        'status': status_enum,
                        'approved_at': timezone.now() if status_enum == SenderID.Status.APPROVED else None
                    }
                )
                if created:
                    synced_count += 1
                else:
                    if sid.status != status_enum:
                        sid.status = status_enum
                        sid.save(update_fields=['status'])

        self.stdout.write(self.style.SUCCESS(f"Successfully synchronized {len(sender_ids)} sender ID(s) ({synced_count} new entries created)."))
