import json
import uuid
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from django.utils import timezone
from accounts.api_auth import require_api_key
from contacts.utils import normalize_phone_number
from billing.ledger_service import CreditLedgerService, InsufficientCreditsError
from .models import SenderID, SMSMessage
from .segmentation import calculate_sms_segments
from .providers import get_sms_provider


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(require_api_key, name='dispatch')
class SendSMSApiView(View):
    """
    POST /api/v1/sms/send
    Enterprise Developer REST API for sending individual transactional SMS.
    Payload:
      {
         "recipient": "0244123456",
         "message": "Your verification code is 849204",
         "sender_id": "IRONFIT" (optional, defaults to business preferred or platform default)
      }
    """
    def post(self, request):
        business = request.business

        try:
            data = json.loads(request.body.decode('utf-8'))
        except Exception:
            data = request.POST.dict()

        raw_phone = data.get('recipient') or data.get('phone') or data.get('to')
        message_text = data.get('message') or data.get('text') or ''
        requested_sender_id = data.get('sender_id') or data.get('from')

        if not raw_phone:
            return JsonResponse({"error": "Bad Request", "message": "Field 'recipient' is required."}, status=400)

        if not message_text.strip():
            return JsonResponse({"error": "Bad Request", "message": "Field 'message' cannot be empty."}, status=400)

        # 1. Normalize phone to E.164 (Ghana 233XXXXXXXXX)
        is_valid, norm_phone, err = normalize_phone_number(raw_phone)
        if not is_valid:
            return JsonResponse({"error": "Unprocessable Entity", "message": f"Invalid phone number: {err}"}, status=422)

        # 2. Resolve & Validate Sender ID
        sender_id = ''
        if requested_sender_id:
            requested_clean = requested_sender_id.strip()
            # Verify it is either owned by this business or a verified system default
            allowed = SenderID.objects.filter(
                sender_id=requested_clean,
                status=SenderID.Status.APPROVED,
                business=business
            ).exists() or SenderID.objects.filter(
                sender_id=requested_clean,
                status=SenderID.Status.APPROVED,
                is_system_default=True
            ).exists()

            if not allowed:
                return JsonResponse({
                    "error": "Forbidden",
                    "message": f"Sender ID '{requested_clean}' is not approved for your workspace. Request it on your dashboard."
                }, status=403)
            sender_id = requested_clean
        else:
            # Fallback to business's primary approved custom ID or platform default
            primary_sid = SenderID.objects.filter(business=business, status=SenderID.Status.APPROVED).first()
            if primary_sid:
                sender_id = primary_sid.sender_id
            else:
                default_sys = SenderID.objects.filter(is_system_default=True, status=SenderID.Status.APPROVED).first()
                sender_id = default_sys.sender_id if default_sys else "TextBridge"

        # 3. Calculate Segments & Cost
        metrics = calculate_sms_segments(message_text)
        credits_needed = metrics['segment_count']

        # 4. Atomic Balance Debit with Row-Level Lock
        tx_ref = f"API_SMS_{uuid.uuid4().hex[:12].upper()}"
        try:
            entry = CreditLedgerService.record_entry(
                business_id=business.id,
                entry_type='CAMPAIGN_USAGE_DEBIT',
                amount=-credits_needed,
                reference_id=tx_ref,
                description=f"REST API SMS sent to {norm_phone} via key '{request.api_key.name}'"
            )
        except InsufficientCreditsError:
            return JsonResponse({
                "error": "Payment Required",
                "message": f"Insufficient credit balance. Required: {credits_needed}, Available: {business.credit_balance}.",
                "required_credits": credits_needed,
                "current_balance": business.credit_balance
            }, status=402)

        # 5. Dispatch via Active Telecom Provider (mNotify)
        provider = get_sms_provider()
        res = provider.send_single(
            sender_id=sender_id,
            recipient_phone=norm_phone,
            message=message_text
        )

        # 6. Record Message
        msg_record = SMSMessage.objects.create(
            business=business,
            recipient_phone=norm_phone,
            sender_id=sender_id,
            message=message_text,
            status=SMSMessage.Status.DELIVERED if res.is_success else SMSMessage.Status.FAILED,
            provider_message_id=res.provider_message_id,
            credits_used=credits_needed
        )

        if not res.is_success:
            # Rollback / Refund credits immediately on provider failure
            CreditLedgerService.record_entry(
                business_id=business.id,
                entry_type='RESERVATION_RELEASE',
                amount=+credits_needed,
                reference_id=f"REL_{tx_ref}",
                description=f"API refund for failed SMS to {norm_phone} ({res.error_message})"
            )
            business.refresh_from_db()
            return JsonResponse({
                "status": "failed",
                "error": "Gateway Error",
                "message": f"Telecom gateway rejected message: {res.error_message}",
                "credits_refunded": credits_needed,
                "remaining_balance": business.credit_balance
            }, status=502)

        business.refresh_from_db()

        return JsonResponse({
            "status": "success",
            "message_id": msg_record.provider_message_id or f"TB_{msg_record.id}",
            "internal_id": msg_record.id,
            "recipient": norm_phone,
            "sender_id": sender_id,
            "segments": credits_needed,
            "is_unicode": metrics['is_unicode'],
            "credits_deducted": credits_needed,
            "remaining_balance": business.credit_balance,
            "delivery_status": msg_record.status,
            "created_at": msg_record.created_at.isoformat()
        }, status=201)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(require_api_key, name='dispatch')
class BalanceApiView(View):
    """
    GET /api/v1/balance
    Returns current SMS credit balance for the authenticated workspace.
    """
    def get(self, request):
        business = request.business
        business.refresh_from_db()
        return JsonResponse({
            "status": "success",
            "business_id": business.id,
            "business_name": business.name,
            "credit_balance": business.credit_balance,
            "currency": "GHS"
        })
