import logging
from django.utils import timezone
from accounts.models import User
from .models import SMSCampaign
from .campaign_service import CampaignService

logger = logging.getLogger(__name__)

try:
    from celery import shared_task
    HAVE_CELERY = True
except ImportError:
    HAVE_CELERY = False


if HAVE_CELERY:
    @shared_task(
        bind=True,
        max_retries=3,
        default_retry_delay=10,
        name='messaging.tasks.dispatch_campaign_async'
    )
    def dispatch_campaign_async(self, campaign_id, actor_id=None):
        """
        Asynchronously broadcasts a campaign in background worker process.
        Prevents HTTP web timeouts on large contact batches (1,000 to 50,000+ recipients).
        """
        logger.info(f"[Celery] Starting async dispatch for Campaign #{campaign_id} (Actor ID: {actor_id})")
        try:
            campaign = SMSCampaign.objects.get(id=campaign_id)
            actor = User.objects.filter(id=actor_id).first() if actor_id else None
            
            result = CampaignService.dispatch_campaign(campaign, actor=actor)
            logger.info(f"[Celery] Campaign #{campaign_id} dispatch completed: {result}")
            return {
                'campaign_id': campaign_id,
                'status': 'SUCCESS',
                'delivered': result.get('delivered_count', 0),
                'failed': result.get('failed_count', 0),
                'actual_credits_used': result.get('actual_credits_used', 0)
            }
        except Exception as exc:
            logger.error(f"[Celery] Error in dispatch_campaign_async for #{campaign_id}: {exc}")
            # Do not retry on business balance errors
            if "Insufficient" in str(exc) or "already running" in str(exc):
                return {'campaign_id': campaign_id, 'status': 'ABORTED', 'error': str(exc)}
            raise self.retry(exc=exc)

    @shared_task(name='messaging.tasks.process_scheduled_campaigns_task')
    def process_scheduled_campaigns_task():
        """
        Periodic Celery Beat task that triggers campaigns scheduled for the current timestamp.
        """
        now = timezone.now()
        due_campaigns = SMSCampaign.objects.filter(
            status=SMSCampaign.Status.QUEUED,
            is_scheduled=True,
            scheduled_at__lte=now
        )
        dispatched_count = 0
        for campaign in due_campaigns:
            dispatch_campaign_async.delay(campaign.id)
            dispatched_count += 1
            logger.info(f"[Celery Beat] Triggered scheduled Campaign #{campaign.id} ('{campaign.title}')")
            
        return f"Triggered {dispatched_count} scheduled campaign(s) at {now}"

else:
    def dispatch_campaign_async(campaign_id, actor_id=None):
        campaign = SMSCampaign.objects.get(id=campaign_id)
        actor = User.objects.filter(id=actor_id).first() if actor_id else None
        return CampaignService.dispatch_campaign(campaign, actor=actor)

    def process_scheduled_campaigns_task():
        pass
