import json
import logging
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.generic import View
from django.contrib import messages
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from accounts.decorators import tenant_required
from billing.ledger_service import CreditLedgerService, InsufficientCreditsError
from .models import SMSCampaign, CampaignRecipient, SenderID, SMSMessage
from .forms import CampaignComposeForm, SenderIDForm, SingleMessageForm
from .campaign_service import CampaignService, CampaignExecutionError
from .segmentation import calculate_sms_segments
from .providers import get_sms_provider
from .tasks import dispatch_campaign_async

logger = logging.getLogger(__name__)


class CampaignListView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        campaigns = SMSCampaign.objects.filter(business=business).order_by('-created_at')

        return render(request, 'messaging/campaign_list.html', {
            'campaigns': campaigns,
            'balance': business.credit_balance
        })


class CampaignCreateView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        form = CampaignComposeForm(business=business)
        return render(request, 'messaging/campaign_compose.html', {
            'form': form,
            'balance': business.credit_balance
        })

    @tenant_required
    def post(self, request):
        business = request.business
        form = CampaignComposeForm(request.POST, business=business)
        if form.is_valid():
            campaign = form.save(commit=False)
            campaign.business = business
            campaign.status = SMSCampaign.Status.SCHEDULED if campaign.is_scheduled else SMSCampaign.Status.DRAFT
            campaign.save()

            # Pre-calculate recipients and required credits
            prep_info = CampaignService.prepare_recipients(campaign)

            if not campaign.is_scheduled:
                # 1. Asynchronous Celery Dispatch (Production Mode)
                if getattr(settings, 'USE_CELERY', False):
                    try:
                        campaign.status = SMSCampaign.Status.QUEUED
                        campaign.save(update_fields=['status'])
                        dispatch_campaign_async.delay(campaign.id, actor_id=request.user.id)
                        messages.success(
                            request,
                            f"Campaign '{campaign.title}' queued for background telecom dispatch! "
                            f"Targeting {prep_info['valid_recipients']} recipient(s). Progress updates in real time below."
                        )
                        return redirect('messaging:campaign_detail', pk=campaign.id)
                    except Exception as e:
                        logger.warning(f"Celery queueing failed ({e}), falling back to direct synchronous dispatch.")

                # 2. Synchronous Execution (Development Fallback)
                try:
                    dispatch_res = CampaignService.dispatch_campaign(campaign, actor=request.user)
                    messages.success(
                        request,
                        f"Campaign '{campaign.title}' dispatched! Delivered: {dispatch_res['delivered_count']}, "
                        f"Failed: {dispatch_res['failed_count']}. Credits used: {dispatch_res['actual_credits_used']}."
                    )
                    return redirect('messaging:campaign_detail', pk=campaign.id)
                except InsufficientCreditsError as e:
                    messages.error(request, str(e))
                    return redirect('billing:packages')
                except CampaignExecutionError as e:
                    messages.error(request, f"Dispatch error: {str(e)}")
                    return redirect('messaging:campaign_detail', pk=campaign.id)
            else:
                sched_str = campaign.scheduled_at.strftime("%b %d, %Y at %H:%M") if campaign.scheduled_at else ""
                messages.success(
                    request,
                    f"Campaign '{campaign.title}' scheduled for automated broadcast on {sched_str}. "
                    f"Targeting {prep_info['valid_recipients']} recipient(s) ({prep_info['estimated_credits']} credits estimated)."
                )
                return redirect('messaging:campaign_detail', pk=campaign.id)

        return render(request, 'messaging/campaign_compose.html', {
            'form': form,
            'balance': business.credit_balance
        })


class CampaignDetailView(View):
    @tenant_required
    def get(self, request, pk):
        business = request.business
        campaign = get_object_or_404(SMSCampaign, pk=pk, business=business)
        recipients = campaign.recipients.all()

        delivered_count = recipients.filter(status='DELIVERED').count()
        accepted_count = recipients.filter(status='ACCEPTED').count()
        failed_count = recipients.filter(status='FAILED').count()
        queued_count = recipients.filter(status='QUEUED').count()

        return render(request, 'messaging/campaign_detail.html', {
            'campaign': campaign,
            'recipients': recipients[:100],  # show first 100 on page
            'total_recipient_records': recipients.count(),
            'delivered_count': delivered_count,
            'accepted_count': accepted_count,
            'failed_count': failed_count,
            'queued_count': queued_count,
        })


class CampaignCancelView(View):
    @tenant_required
    def post(self, request, pk):
        business = request.business
        campaign = get_object_or_404(SMSCampaign, pk=pk, business=business)
        if campaign.status in [SMSCampaign.Status.DRAFT, SMSCampaign.Status.QUEUED, SMSCampaign.Status.SCHEDULED]:
            campaign.status = SMSCampaign.Status.CANCELLED
            campaign.save(update_fields=['status'])
            messages.success(request, f"Campaign '{campaign.title}' has been successfully cancelled.")
        else:
            messages.error(request, "Only scheduled, queued, or draft campaigns can be cancelled.")
        return redirect('messaging:campaign_detail', pk=campaign.id)


class SenderIDListView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        sender_ids = SenderID.objects.filter(business=business).order_by('-created_at')
        system_sender_ids = SenderID.objects.filter(is_system_default=True, status=SenderID.Status.APPROVED).order_by('sender_id')
        form = SenderIDForm()
        return render(request, 'messaging/sender_id_list.html', {
            'sender_ids': sender_ids,
            'system_sender_ids': system_sender_ids,
            'form': form
        })

    @tenant_required
    def post(self, request):
        business = request.business
        form = SenderIDForm(request.POST)
        if form.is_valid():
            sid = form.save(commit=False)
            sid.business = business
            sid.is_system_default = False
            
            # Check for duplicates
            if SenderID.objects.filter(business=business, sender_id=sid.sender_id).exists():
                messages.error(request, f"Sender ID '{sid.sender_id}' is already registered for your account.")
            elif SenderID.objects.filter(is_system_default=True, sender_id=sid.sender_id).exists():
                messages.info(request, f"'{sid.sender_id}' is already available to your workspace as a Platform Default.")
            else:
                sid.status = SenderID.Status.PENDING
                sid.save()
                messages.success(request, f"Sender ID '{sid.sender_id}' submitted for telco whitelisting. Review typically takes 24 hours.")
            return redirect('messaging:sender_ids')

        sender_ids = SenderID.objects.filter(business=business).order_by('-created_at')
        system_sender_ids = SenderID.objects.filter(is_system_default=True, status=SenderID.Status.APPROVED).order_by('sender_id')
        return render(request, 'messaging/sender_id_list.html', {
            'sender_ids': sender_ids,
            'system_sender_ids': system_sender_ids,
            'form': form
        })


class SingleTestMessageView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        form = SingleMessageForm(business=business)
        return render(request, 'messaging/single_message.html', {
            'form': form,
            'balance': business.credit_balance
        })

    @tenant_required
    def post(self, request):
        business = request.business
        form = SingleMessageForm(request.POST, business=business)
        if form.is_valid():
            sender_id = form.cleaned_data['sender_id']
            phone = form.cleaned_data['recipient_phone']
            msg_text = form.cleaned_data['message']

            metrics = calculate_sms_segments(msg_text)
            credits_needed = metrics['segment_count']

            if business.credit_balance < credits_needed:
                messages.error(
                    request,
                    f"Insufficient credits. This message requires {credits_needed} credit(s), but your balance is {business.credit_balance}."
                )
                return redirect('billing:packages')

            # Atomically debit
            import uuid
            tx_ref = f"DIRECT_SMS_{uuid.uuid4().hex[:10].upper()}"
            try:
                CreditLedgerService.record_entry(
                    business_id=business.id,
                    entry_type='CAMPAIGN_USAGE_DEBIT',
                    amount=-credits_needed,
                    reference_id=tx_ref,
                    description=f"Direct SMS sent to {phone}",
                    actor=request.user
                )
            except InsufficientCreditsError:
                messages.error(request, "Insufficient credit balance.")
                return redirect('billing:packages')

            provider = get_sms_provider()
            res = provider.send_single(sender_id=sender_id, recipient_phone=phone, message=msg_text)

            SMSMessage.objects.create(
                business=business,
                recipient_phone=phone,
                sender_id=sender_id,
                message=msg_text,
                status=SMSMessage.Status.DELIVERED if res.is_success else SMSMessage.Status.FAILED,
                provider_message_id=res.provider_message_id,
                credits_used=credits_needed
            )

            if res.is_success:
                messages.success(request, f"Message dispatched to {phone} successfully ({credits_needed} credit used)!")
            else:
                # Release credit on failure
                CreditLedgerService.record_entry(
                    business_id=business.id,
                    entry_type='RESERVATION_RELEASE',
                    amount=+credits_needed,
                    reference_id=f"REL_{tx_ref}",
                    description=f"Refunded {credits_needed} credit for failed direct SMS to {phone}",
                    actor=request.user
                )
                messages.error(request, f"Failed to send message: {res.error_message}. Your credit was restored.")

            return redirect('messaging:single_message')

        return render(request, 'messaging/single_message.html', {
            'form': form,
            'balance': business.credit_balance
        })


class CalculateSegmentsApiView(View):
    def post(self, request):
        try:
            data = json.loads(request.body.decode('utf-8'))
            text = data.get('text', '')
            metrics = calculate_sms_segments(text)
            return JsonResponse(metrics)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class MNotifyDlrWebhookView(View):
    """
    Inbound Delivery Reports (DLR) webhook listener for telecom gateways (mNotify).
    Updates individual recipient and direct message statuses when telco reports back:
    e.g. DELIVERED, FAILED, UNDELIVERED, EXPIRED, REJECTED.
    """
    def get(self, request):
        return JsonResponse({
            "status": "active",
            "service": "TextBridge Telecom DLR Webhook",
            "provider": "mNotify"
        })

    def post(self, request):
        payload = {}
        if request.content_type == 'application/json' or request.body:
            try:
                payload = json.loads(request.body.decode('utf-8'))
            except Exception:
                payload = request.POST.dict()
        else:
            payload = request.POST.dict()

        logger.info(f"mNotify DLR Webhook received: {payload}")

        # Extract message identifier and status
        message_id = (
            payload.get('message_id') or 
            payload.get('id') or 
            payload.get('msg_id') or 
            payload.get('provider_message_id') or 
            payload.get('custom_id')
        )
        raw_status = str(
            payload.get('status') or 
            payload.get('delivery_status') or 
            payload.get('dlr_status') or 
            ''
        ).upper()
        recipient_phone = payload.get('recipient') or payload.get('phone') or payload.get('to')
        error_msg = payload.get('error') or payload.get('reason') or payload.get('network_error') or ''

        # Map to internal statuses
        target_status = None
        if raw_status in ['DELIVERED', 'SUCCESS', 'DELIVRD']:
            target_status = CampaignRecipient.Status.DELIVERED
        elif raw_status in ['FAILED', 'UNDELIVERED', 'UNDELIV', 'EXPIRED', 'REJECTED']:
            target_status = CampaignRecipient.Status.FAILED

        updated_count = 0

        if message_id:
            # 1. Update Campaign Recipients
            recipients = CampaignRecipient.objects.filter(provider_message_id=str(message_id))
            for r in recipients:
                if target_status:
                    r.status = target_status
                if error_msg:
                    r.error_message = error_msg
                r.save(update_fields=['status', 'error_message', 'updated_at'])
                updated_count += 1

                # Reconcile campaign aggregate status
                campaign = r.campaign
                pending = campaign.recipients.filter(status__in=[
                    CampaignRecipient.Status.QUEUED,
                    CampaignRecipient.Status.SUBMITTED,
                    CampaignRecipient.Status.ACCEPTED
                ]).count()
                if pending == 0:
                    failures = campaign.recipients.filter(status=CampaignRecipient.Status.FAILED).count()
                    if failures == 0:
                        campaign.status = SMSCampaign.Status.COMPLETED
                    else:
                        campaign.status = SMSCampaign.Status.PARTIAL_FAILURE
                    campaign.completed_at = timezone.now()
                    campaign.save(update_fields=['status', 'completed_at'])

            # 2. Update Direct Single Messages
            direct_msgs = SMSMessage.objects.filter(provider_message_id=str(message_id))
            for msg in direct_msgs:
                if target_status == CampaignRecipient.Status.DELIVERED:
                    msg.status = SMSMessage.Status.DELIVERED
                elif target_status == CampaignRecipient.Status.FAILED:
                    msg.status = SMSMessage.Status.FAILED
                msg.save(update_fields=['status'])
                updated_count += 1

        elif recipient_phone and target_status:
            # Fallback by recipient phone if message_id was omitted
            recent = CampaignRecipient.objects.filter(
                phone_number=recipient_phone,
                status__in=[CampaignRecipient.Status.SUBMITTED, CampaignRecipient.Status.ACCEPTED]
            ).order_by('-updated_at').first()
            if recent:
                recent.status = target_status
                if error_msg:
                    recent.error_message = error_msg
                recent.save(update_fields=['status', 'error_message', 'updated_at'])
                updated_count += 1

        return JsonResponse({
            "status": "success",
            "message": f"DLR processed successfully. {updated_count} record(s) updated.",
            "updated_records": updated_count
        })
