from django.core.management.base import BaseCommand
from django.utils import timezone
from messaging.models import SMSCampaign
from messaging.campaign_service import CampaignService, CampaignExecutionError
from billing.ledger_service import InsufficientCreditsError


class Command(BaseCommand):
    help = 'Processes and dispatches queued SMS campaigns whose scheduled time has arrived'

    def handle(self, *args, **options):
        now = timezone.now()
        due_campaigns = SMSCampaign.objects.filter(
            status=SMSCampaign.Status.QUEUED,
            is_scheduled=True,
            scheduled_at__lte=now
        )

        count = due_campaigns.count()
        if count == 0:
            self.stdout.write("No scheduled campaigns are due for dispatch.")
            return

        self.stdout.write(f"Found {count} campaign(s) due for dispatch...")

        for campaign in due_campaigns:
            self.stdout.write(f"Processing Campaign #{campaign.id}: '{campaign.title}' ({campaign.business.name})...")
            try:
                res = CampaignService.dispatch_campaign(campaign)
                self.stdout.write(self.style.SUCCESS(
                    f"Campaign #{campaign.id} completed: Delivered={res['delivered_count']}, Failed={res['failed_count']}"
                ))
            except InsufficientCreditsError as e:
                self.stdout.write(self.style.ERROR(
                    f"Campaign #{campaign.id} failed due to insufficient credits: {str(e)}"
                ))
            except CampaignExecutionError as e:
                self.stdout.write(self.style.ERROR(
                    f"Campaign #{campaign.id} execution error: {str(e)}"
                ))
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"Unexpected error on campaign #{campaign.id}: {str(e)}"
                ))
