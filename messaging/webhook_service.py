import json
import time
import uuid
import hmac
import hashlib
import logging
import requests
from django.utils import timezone
from .models import WebhookEndpoint, WebhookDelivery

logger = logging.getLogger(__name__)


class WebhookService:
    @classmethod
    def dispatch_event(cls, business, event_type: str, data: dict) -> list:
        """
        Dispatches an event to all active endpoints registered for the business
        that are subscribed to the specified event_type.
        """
        endpoints = WebhookEndpoint.objects.filter(
            business=business,
            is_active=True
        )

        deliveries = []
        for endpoint in endpoints:
            if endpoint.events and event_type not in endpoint.events and '*' not in endpoint.events:
                continue

            delivery = cls._deliver_to_endpoint(endpoint, event_type, data)
            deliveries.append(delivery)

        return deliveries

    @classmethod
    def _deliver_to_endpoint(cls, endpoint: WebhookEndpoint, event_type: str, data: dict) -> WebhookDelivery:
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        now_iso = timezone.now().isoformat()

        payload = {
            "id": event_id,
            "event": event_type,
            "timestamp": now_iso,
            "business": {
                "id": endpoint.business.id,
                "name": endpoint.business.name
            },
            "data": data
        }

        body_str = json.dumps(payload, separators=(',', ':'))

        # Calculate HMAC-SHA256 signature
        signature = hmac.new(
            endpoint.secret_key.encode('utf-8'),
            body_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "TextBridge-Webhook/1.0",
            "X-TextBridge-Event": event_type,
            "X-TextBridge-Signature": signature,
            "X-TextBridge-Delivery": event_id,
        }

        status_code = None
        resp_text = ""
        error_msg = ""
        is_success = False

        start_time = time.time()
        try:
            resp = requests.post(
                endpoint.url,
                data=body_str,
                headers=headers,
                timeout=5
            )
            duration_ms = int((time.time() - start_time) * 1000)
            status_code = resp.status_code
            resp_text = resp.text[:500]
            is_success = (200 <= status_code < 300)
            if not is_success:
                error_msg = f"Remote endpoint returned HTTP {status_code}"
        except requests.RequestException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)[:300]
            logger.warning(f"[Webhook] Delivery failed to {endpoint.url}: {error_msg}")

        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event_type=event_type,
            event_id=event_id,
            payload=payload,
            response_status_code=status_code,
            response_body=resp_text,
            duration_ms=duration_ms,
            is_success=is_success,
            error_message=error_msg
        )
        return delivery

    @classmethod
    def trigger_sms_status(cls, message_obj, event_type: str = None):
        """
        Triggers an sms.sent, sms.delivered, or sms.failed event.
        """
        status = getattr(message_obj, 'status', '').upper()
        if not event_type:
            if status in ['DELIVERED', 'ACCEPTED']:
                event_type = 'sms.delivered'
            elif status == 'FAILED':
                event_type = 'sms.failed'
            else:
                event_type = 'sms.sent'

        phone = getattr(message_obj, 'recipient_phone', None) or getattr(message_obj, 'phone_number', '')
        provider_id = getattr(message_obj, 'provider_message_id', '')
        sender_id = getattr(message_obj, 'sender_id', '')

        data = {
            "internal_id": message_obj.id,
            "provider_message_id": provider_id,
            "recipient": phone,
            "sender_id": sender_id,
            "status": status,
            "credits_used": getattr(message_obj, 'credits_used', 1),
        }
        return cls.dispatch_event(message_obj.business, event_type, data)

    @classmethod
    def trigger_campaign_completed(cls, campaign):
        data = {
            "campaign_id": campaign.id,
            "title": campaign.title,
            "sender_id": campaign.sender_id,
            "total_recipients": campaign.total_recipients,
            "valid_recipients": campaign.valid_recipients_count,
            "actual_credits_used": campaign.actual_credits_used,
            "status": campaign.status,
            "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
            "completed_at": campaign.completed_at.isoformat() if campaign.completed_at else None,
        }
        return cls.dispatch_event(campaign.business, 'campaign.completed', data)

    @classmethod
    def send_test_ping(cls, endpoint: WebhookEndpoint) -> WebhookDelivery:
        """
        Sends a test event to verify the endpoint is online and responsive.
        """
        test_data = {
            "message": "This is a test notification from TextBridge SMS platform.",
            "test_mode": True,
            "endpoint_id": endpoint.id,
            "url": endpoint.url,
            "supported_events": endpoint.events
        }
        return cls._deliver_to_endpoint(endpoint, "endpoint.test_ping", test_data)
