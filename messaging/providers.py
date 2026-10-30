import uuid
import requests
from django.conf import settings
from decimal import Decimal


class ProviderSendResult:
    def __init__(self, is_success: bool, provider_message_id: str = '', status: str = 'SUBMITTED', error_message: str = '', raw_response: dict = None):
        self.is_success = is_success
        self.provider_message_id = provider_message_id
        self.status = status
        self.error_message = error_message
        self.raw_response = raw_response or {}


class BaseSMSProvider:
    def send_single(self, sender_id: str, recipient_phone: str, message: str) -> ProviderSendResult:
        raise NotImplementedError

    def send_bulk(self, sender_id: str, recipient_phones: list[str], message: str) -> ProviderSendResult:
        raise NotImplementedError

    def get_balance(self) -> dict:
        raise NotImplementedError

    def get_delivery_status(self, provider_message_id: str) -> str:
        raise NotImplementedError


class MockSMSProvider(BaseSMSProvider):
    """
    Safe simulated SMS Gateway for development and testing.
    Never sends live messages or spends actual money.
    """

    def send_single(self, sender_id: str, recipient_phone: str, message: str) -> ProviderSendResult:
        # Simulate network failure if phone ends in 0000
        if str(recipient_phone).endswith('0000'):
            return ProviderSendResult(
                is_success=False,
                status='FAILED',
                error_message="Simulated Gateway Failure: Destination number invalid or unreachable",
                raw_response={'mock': True, 'error': 'destination_unreachable'}
            )

        msg_id = f"MOCK_{uuid.uuid4().hex[:12].upper()}"
        return ProviderSendResult(
            is_success=True,
            provider_message_id=msg_id,
            status='DELIVERED',
            raw_response={'mock': True, 'id': msg_id, 'status': 'Delivered (Simulated)'}
        )

    def send_bulk(self, sender_id: str, recipient_phones: list[str], message: str) -> ProviderSendResult:
        batch_id = f"MOCK_BATCH_{uuid.uuid4().hex[:10].upper()}"
        return ProviderSendResult(
            is_success=True,
            provider_message_id=batch_id,
            status='ACCEPTED',
            raw_response={'mock': True, 'batch_id': batch_id, 'recipients_count': len(recipient_phones)}
        )

    def get_balance(self) -> dict:
        return {
            'is_mock': True,
            'balance': Decimal('15000.00'),
            'currency': 'GHS',
            'status': 'Connected (Simulated Local Sandbox)'
        }

    def get_delivery_status(self, provider_message_id: str) -> str:
        return 'DELIVERED'

    def get_approved_sender_ids(self) -> list[dict]:
        return [{'sender_name': 'BRIGHTSMS', 'status': 'approved'}]


class MNotifySMSProvider(BaseSMSProvider):
    """
    Official mNotify SMS Gateway Adapter (Ghana).
    Documentation: https://developer.mnotify.com
    Base URL: https://api.mnotify.com/api
    """

    def __init__(self):
        self.api_key = getattr(settings, 'MNOTIFY_API_KEY', '')
        self.base_url = getattr(settings, 'MNOTIFY_BASE_URL', 'https://api.mnotify.com/api').rstrip('/')

    def _headers(self):
        return {
            'Content-Type': 'application/json',
        }

    def send_single(self, sender_id: str, recipient_phone: str, message: str) -> ProviderSendResult:
        if not self.api_key:
            return ProviderSendResult(
                is_success=False,
                status='FAILED',
                error_message="mNotify API Key is not configured on the server."
            )

        url = f"{self.base_url}/sms/quick?key={self.api_key}"
        payload = {
            'recipient': [recipient_phone],
            'sender': sender_id,
            'message': message,
            'is_schedule': False
        }

        try:
            response = requests.post(url, json=payload, headers=self._headers(), timeout=15)
            data = response.json()
            if response.status_code in (200, 201) and data.get('status') == 'success':
                msg_id = str(data.get('summary', {}).get('_id', uuid.uuid4().hex[:10]))
                return ProviderSendResult(
                    is_success=True,
                    provider_message_id=msg_id,
                    status='ACCEPTED',
                    raw_response=data
                )
            else:
                err = data.get('message', 'Provider rejected the message')
                return ProviderSendResult(
                    is_success=False,
                    status='REJECTED',
                    error_message=err,
                    raw_response=data
                )
        except requests.RequestException as e:
            return ProviderSendResult(
                is_success=False,
                status='FAILED',
                error_message=f"mNotify connection error: {str(e)}"
            )

    def send_bulk(self, sender_id: str, recipient_phones: list[str], message: str) -> ProviderSendResult:
        if not self.api_key:
            return ProviderSendResult(
                is_success=False,
                status='FAILED',
                error_message="mNotify API Key is not configured on the server."
            )

        url = f"{self.base_url}/sms/quick?key={self.api_key}"
        payload = {
            'recipient': recipient_phones,
            'sender': sender_id,
            'message': message,
            'is_schedule': False
        }

        try:
            response = requests.post(url, json=payload, headers=self._headers(), timeout=25)
            data = response.json()
            if response.status_code in (200, 201) and data.get('status') == 'success':
                summary = data.get('summary', {})
                batch_id = str(summary.get('_id', uuid.uuid4().hex[:10]))
                return ProviderSendResult(
                    is_success=True,
                    provider_message_id=batch_id,
                    status='ACCEPTED',
                    raw_response=data
                )
            else:
                err = data.get('message', 'Provider rejected bulk campaign')
                return ProviderSendResult(
                    is_success=False,
                    status='REJECTED',
                    error_message=err,
                    raw_response=data
                )
        except requests.RequestException as e:
            return ProviderSendResult(
                is_success=False,
                status='FAILED',
                error_message=f"mNotify connection error: {str(e)}"
            )

    def get_balance(self) -> dict:
        if not self.api_key:
            return {'is_mock': False, 'balance': Decimal('0.00'), 'currency': 'GHS', 'status': 'API Key not set'}

        url = f"{self.base_url}/balance/sms?key={self.api_key}"
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
            if response.status_code == 200 and data.get('status') == 'success':
                balance_val = data.get('balance', 0)
                return {
                    'is_mock': False,
                    'balance': Decimal(str(balance_val)),
                    'currency': 'GHS',
                    'status': 'Connected'
                }
            return {
                'is_mock': False,
                'balance': Decimal('0.00'),
                'currency': 'GHS',
                'status': data.get('message', 'Failed to retrieve balance')
            }
        except requests.RequestException as e:
            return {
                'is_mock': False,
                'balance': Decimal('0.00'),
                'currency': 'GHS',
                'status': f"Connection Error: {str(e)}"
            }

    def get_delivery_status(self, provider_message_id: str) -> str:
        # mNotify status lookup
        return 'ACCEPTED'

    def get_approved_sender_ids(self) -> list[dict]:
        """
        Fetches approved sender IDs from mNotify gateway account.
        """
        if not self.api_key:
            return []
        url = f"{self.base_url}/senderid?key={self.api_key}"
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
            if response.status_code == 200 and data.get('status') == 'success':
                return data.get('summary', [])
            return []
        except requests.RequestException:
            return []


def get_sms_provider() -> BaseSMSProvider:
    provider_type = getattr(settings, 'ACTIVE_SMS_PROVIDER', 'MOCK').upper()
    if provider_type == 'MNOTIFY':
        return MNotifySMSProvider()
    return MockSMSProvider()
