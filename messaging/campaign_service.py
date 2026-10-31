from django.utils import timezone
from django.db import transaction
from contacts.models import Contact, SuppressionRecord, ContactGroupMembership
from billing.ledger_service import CreditLedgerService, InsufficientCreditsError
from .models import SMSCampaign, CampaignRecipient
from .segmentation import calculate_sms_segments
from .providers import get_sms_provider


class CampaignExecutionError(Exception):
    pass


class CampaignService:
    @classmethod
    def prepare_recipients(cls, campaign: SMSCampaign) -> dict:
        """
        Gathers contacts, filters suppressed/unsubscribed contacts, renders personalization,
        creates CampaignRecipient records, and calculates credits required.
        """
        business = campaign.business

        # Gather target contacts
        if campaign.target_group:
            contacts = Contact.objects.filter(
                business=business,
                group_memberships__group=campaign.target_group
            ).distinct()
        else:
            contacts = Contact.objects.filter(business=business)

        from django.db.models import Q
        suppressed_numbers = set(
            SuppressionRecord.objects.filter(
                Q(business=business) | Q(business__isnull=True)
            ).values_list('phone_number', flat=True)
        )

        # Clear any prior draft recipients
        campaign.recipients.all().delete()

        valid_count = 0
        suppressed_count = 0
        total_credits = 0

        recipient_objects = []

        for contact in contacts:
            # Check unsubscribe or suppression
            if not contact.is_subscribed or contact.phone_number in suppressed_numbers:
                suppressed_count += 1
                continue

            # Personalize message: replace {{name}}, {{first_name}}, {{phone}}
            first_name = contact.name.split()[0] if contact.name else ''
            rendered_msg = campaign.message_template.replace('{{name}}', contact.name)
            rendered_msg = rendered_msg.replace('{{first_name}}', first_name)
            rendered_msg = rendered_msg.replace('{{phone}}', contact.phone_number)

            metrics = calculate_sms_segments(rendered_msg)
            seg_count = metrics['segment_count']
            credits_needed = seg_count  # 1 credit per segment

            valid_count += 1
            total_credits += credits_needed

            recipient_objects.append(
                CampaignRecipient(
                    campaign=campaign,
                    contact=contact,
                    phone_number=contact.phone_number,
                    recipient_name=contact.name,
                    rendered_message=rendered_msg,
                    segments_count=seg_count,
                    credits_used=credits_needed,
                    status=CampaignRecipient.Status.QUEUED
                )
            )

        CampaignRecipient.objects.bulk_create(recipient_objects)

        campaign.total_recipients = contacts.count()
        campaign.valid_recipients_count = valid_count
        campaign.suppressed_recipients_count = suppressed_count
        campaign.estimated_credits = total_credits
        campaign.save(update_fields=[
            'total_recipients',
            'valid_recipients_count',
            'suppressed_recipients_count',
            'estimated_credits'
        ])

        return {
            'total_contacts': contacts.count(),
            'valid_recipients': valid_count,
            'suppressed_recipients': suppressed_count,
            'estimated_credits': total_credits
        }

    @classmethod
    def dispatch_campaign(cls, campaign: SMSCampaign, actor=None) -> dict:
        """
        Executes campaign delivery with atomic balance reservation, gateway submission,
        and reconciliation of unused credits.
        """
        if campaign.status in [SMSCampaign.Status.COMPLETED, SMSCampaign.Status.PROCESSING]:
            raise CampaignExecutionError("This campaign is already running or completed.")

        # Ensure recipients are prepared
        if campaign.valid_recipients_count == 0 or not campaign.recipients.exists():
            cls.prepare_recipients(campaign)

        if campaign.valid_recipients_count == 0:
            campaign.status = SMSCampaign.Status.FAILED
            campaign.save(update_fields=['status'])
            raise CampaignExecutionError("No valid recipients to send to (all contacts are suppressed or group is empty).")

        required_credits = campaign.estimated_credits
        business = campaign.business
        business.refresh_from_db()

        if business.credit_balance < required_credits:
            raise InsufficientCreditsError(
                f"Insufficient credits. Required: {required_credits}, Available: {business.credit_balance}. "
                f"Please top up your SMS package."
            )

        reservation_ref = f"CAMP_RES_{campaign.id}_{timezone.now().timestamp()}"

        # 1. Reserve credits atomically
        CreditLedgerService.record_entry(
            business_id=business.id,
            entry_type='CAMPAIGN_RESERVATION',
            amount=-required_credits,
            reference_id=reservation_ref,
            description=f"Credit hold for campaign '{campaign.title}'",
            campaign_id=campaign.id,
            actor=actor
        )

        campaign.status = SMSCampaign.Status.PROCESSING
        campaign.started_at = timezone.now()
        campaign.save(update_fields=['status', 'started_at'])

        provider = get_sms_provider()

        actual_credits_used = 0
        delivered_count = 0
        failed_count = 0

        # 2. Transmit messages to SMS gateway
        recipients = list(campaign.recipients.filter(status=CampaignRecipient.Status.QUEUED))

        for recipient in recipients:
            res = provider.send_single(
                sender_id=campaign.sender_id,
                recipient_phone=recipient.phone_number,
                message=recipient.rendered_message
            )

            if res.is_success:
                recipient.status = CampaignRecipient.Status.ACCEPTED if res.status == 'ACCEPTED' else CampaignRecipient.Status.DELIVERED
                recipient.provider_message_id = res.provider_message_id
                recipient.save(update_fields=['status', 'provider_message_id', 'updated_at'])
                actual_credits_used += recipient.credits_used
                delivered_count += 1
            else:
                recipient.status = CampaignRecipient.Status.FAILED
                recipient.error_message = res.error_message
                recipient.save(update_fields=['status', 'error_message', 'updated_at'])
                failed_count += 1

        # 3. Reconcile differences: release credits for failed submissions
        unused_credits = required_credits - actual_credits_used
        if unused_credits > 0:
            release_ref = f"CAMP_REL_{campaign.id}_{timezone.now().timestamp()}"
            CreditLedgerService.record_entry(
                business_id=business.id,
                entry_type='RESERVATION_RELEASE',
                amount=unused_credits,
                reference_id=release_ref,
                description=f"Released {unused_credits} unused credits from campaign '{campaign.title}'",
                campaign_id=campaign.id,
                actor=actor
            )

        campaign.actual_credits_used = actual_credits_used
        campaign.completed_at = timezone.now()

        if delivered_count > 0 and failed_count == 0:
            campaign.status = SMSCampaign.Status.COMPLETED
        elif delivered_count > 0 and failed_count > 0:
            campaign.status = SMSCampaign.Status.PARTIAL_FAILURE
        else:
            campaign.status = SMSCampaign.Status.FAILED

        campaign.save(update_fields=['actual_credits_used', 'completed_at', 'status'])

        return {
            'campaign_id': campaign.id,
            'status': campaign.status,
            'delivered_count': delivered_count,
            'failed_count': failed_count,
            'actual_credits_used': actual_credits_used,
            'credits_refunded': unused_credits
        }

    @classmethod
    def process_due_scheduled_campaigns(cls) -> dict:
        """
        Finds all campaigns in SCHEDULED status whose scheduled_at time has arrived,
        validates credit availability, and dispatches them.
        """
        now = timezone.now()
        due_campaigns = SMSCampaign.objects.filter(
            status=SMSCampaign.Status.SCHEDULED,
            is_scheduled=True,
            scheduled_at__lte=now
        ).select_related('business').order_by('scheduled_at')

        summary = {
            'due_count': due_campaigns.count(),
            'dispatched_count': 0,
            'failed_count': 0,
            'errors': []
        }

        for campaign in due_campaigns:
            try:
                cls.dispatch_campaign(campaign)
                summary['dispatched_count'] += 1
            except InsufficientCreditsError as e:
                campaign.status = SMSCampaign.Status.FAILED
                campaign.save(update_fields=['status'])
                summary['failed_count'] += 1
                summary['errors'].append(f"Campaign #{campaign.id} ('{campaign.title}'): Insufficient credits ({str(e)})")
            except Exception as e:
                campaign.status = SMSCampaign.Status.FAILED
                campaign.save(update_fields=['status'])
                summary['failed_count'] += 1
                summary['errors'].append(f"Campaign #{campaign.id} ('{campaign.title}'): {str(e)}")

        return summary

