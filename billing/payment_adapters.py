import hmac
import hashlib
import json
import requests
from django.conf import settings
from decimal import Decimal


class PaymentVerificationResult:
    def __init__(self, is_success: bool, amount: Decimal, currency: str, reference: str, provider_fee: Decimal = Decimal('0.00'), raw_data: dict = None, error_message: str = ''):
        self.is_success = is_success
        self.amount = amount
        self.currency = currency
        self.reference = reference
        self.provider_fee = provider_fee
        self.raw_data = raw_data or {}
        self.error_message = error_message


class BasePaymentAdapter:
    def initialize_transaction(self, purchase, callback_url: str) -> dict:
        raise NotImplementedError

    def verify_transaction(self, reference: str) -> PaymentVerificationResult:
        raise NotImplementedError

    def verify_webhook_signature(self, request_body: bytes, signature_header: str) -> bool:
        raise NotImplementedError


class PaystackPaymentAdapter(BasePaymentAdapter):
    """
    Official Paystack Integration Adapter for Ghanaian Cedi (GHS) and other currencies.
    Paystack amounts are denominated in pesewas/kobo (i.e. amount * 100).
    """

    def __init__(self):
        self.secret_key = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
        self.public_key = getattr(settings, 'PAYSTACK_PUBLIC_KEY', '')
        self.base_url = getattr(settings, 'PAYSTACK_BASE_URL', 'https://api.paystack.co').rstrip('/')

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/json',
        }

    def initialize_transaction(self, purchase, callback_url: str) -> dict:
        """
        Calls Paystack API: POST /transaction/initialize
        """
        url = f"{self.base_url}/transaction/initialize"
        # Convert GHS to pesewas (x 100)
        amount_pesewas = int(purchase.amount_paid * 100)

        payload = {
            'email': purchase.business.contact_email,
            'amount': amount_pesewas,
            'currency': purchase.currency or 'GHS',
            'reference': purchase.payment_reference,
            'callback_url': callback_url,
            'metadata': {
                'purchase_id': purchase.id,
                'business_id': purchase.business.id,
                'credits': purchase.credits_granted,
                'package_name': purchase.package.name if purchase.package else 'Custom Package'
            }
        }

        try:
            response = requests.post(url, json=payload, headers=self._headers(), timeout=15)
            data = response.json()
            if response.status_code == 200 and data.get('status') is True:
                return {
                    'authorization_url': data['data']['authorization_url'],
                    'access_code': data['data']['access_code'],
                    'reference': purchase.payment_reference,
                }
            else:
                return {
                    'error': data.get('message', 'Failed to initialize Paystack checkout')
                }
        except requests.RequestException as e:
            return {'error': f"Connection to Paystack failed: {str(e)}"}

    def verify_transaction(self, reference: str) -> PaymentVerificationResult:
        """
        Calls Paystack API: GET /transaction/verify/:reference
        """
        url = f"{self.base_url}/transaction/verify/{reference}"
        try:
            response = requests.get(url, headers=self._headers(), timeout=15)
            data = response.json()
            if response.status_code == 200 and data.get('status') is True:
                tx_data = data['data']
                tx_status = tx_data.get('status')
                amount = Decimal(str(tx_data.get('amount', 0))) / Decimal('100.0')
                currency = tx_data.get('currency', 'GHS')
                fees = Decimal(str(tx_data.get('fees', 0) or 0)) / Decimal('100.0')

                is_success = (tx_status == 'success')
                return PaymentVerificationResult(
                    is_success=is_success,
                    amount=amount,
                    currency=currency,
                    reference=reference,
                    provider_fee=fees,
                    raw_data=tx_data,
                    error_message='' if is_success else f"Payment status: {tx_status}"
                )
            else:
                return PaymentVerificationResult(
                    is_success=False,
                    amount=Decimal('0.00'),
                    currency='GHS',
                    reference=reference,
                    raw_data=data,
                    error_message=data.get('message', 'Transaction verification failed')
                )
        except requests.RequestException as e:
            return PaymentVerificationResult(
                is_success=False,
                amount=Decimal('0.00'),
                currency='GHS',
                reference=reference,
                error_message=f"Network error contacting Paystack: {str(e)}"
            )

    def verify_webhook_signature(self, request_body: bytes, signature_header: str) -> bool:
        """
        Verifies Paystack HMAC SHA512 signature on incoming webhook requests.
        """
        if not signature_header or not self.secret_key:
            return False
        computed_hmac = hmac.new(
            self.secret_key.encode('utf-8'),
            request_body,
            hashlib.sha512
        ).hexdigest()
        return hmac.compare_digest(computed_hmac, signature_header)


class SandboxPaymentAdapter(BasePaymentAdapter):
    """
    Safe local development sandbox for instant end-to-end payment testing.
    Never calls external networks and clearly labels simulated transactions.
    """

    def initialize_transaction(self, purchase, callback_url: str) -> dict:
        # Sandbox simulated checkout URL
        from django.urls import reverse
        sandbox_url = reverse('billing:sandbox_checkout', kwargs={'reference': purchase.payment_reference})
        return {
            'authorization_url': sandbox_url,
            'access_code': f"SANDBOX_{purchase.payment_reference}",
            'reference': purchase.payment_reference,
            'is_sandbox': True,
        }

    def verify_transaction(self, reference: str) -> PaymentVerificationResult:
        return PaymentVerificationResult(
            is_success=True,
            amount=Decimal('0.00'),
            currency='GHS',
            reference=reference,
            raw_data={'simulator': 'SandboxPaymentAdapter', 'status': 'success'}
        )

    def verify_webhook_signature(self, request_body: bytes, signature_header: str) -> bool:
        return True


def get_payment_adapter() -> BasePaymentAdapter:
    if getattr(settings, 'PAYMENT_SANDBOX_MODE', True):
        return SandboxPaymentAdapter()
    return PaystackPaymentAdapter()
