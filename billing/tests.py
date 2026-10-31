import hmac
import hashlib
import json
from decimal import Decimal
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from accounts.models import User, Business, BusinessMembership
from billing.models import SMSPackage, Purchase, PaymentTransaction, CreditLedgerEntry
from billing.ledger_service import CreditLedgerService, InsufficientCreditsError, DuplicateTransactionError
from billing.payment_adapters import PaystackPaymentAdapter, PaymentVerificationResult


class CreditLedgerAndBillingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='test@business.com', password='Password123!')
        self.biz = Business.objects.create(name='Test Biz', contact_email='test@business.com', credit_balance=0)
        self.pkg = SMSPackage.objects.create(name='Starter 500', credits=500, price_ghs=Decimal('35.00'))

    def test_credit_addition_and_balance(self):
        # 1. Purchase credit addition
        entry = CreditLedgerService.record_entry(
            business_id=self.biz.id,
            entry_type='PURCHASE_CREDIT',
            amount=500,
            reference_id='TX_TEST_001',
            description='Test purchase',
            actor=self.user
        )
        self.biz.refresh_from_db()
        self.assertEqual(self.biz.credit_balance, 500)
        self.assertEqual(entry.balance_after, 500)

        # 2. Duplicate prevention (Idempotency)
        with self.assertRaises(DuplicateTransactionError):
            CreditLedgerService.record_entry(
                business_id=self.biz.id,
                entry_type='PURCHASE_CREDIT',
                amount=500,
                reference_id='TX_TEST_001',  # same reference
                description='Duplicate attempt',
                actor=self.user
            )

    def test_insufficient_credits_prevention(self):
        # Attempting to debit more than available must fail and keep balance intact
        with self.assertRaises(InsufficientCreditsError):
            CreditLedgerService.record_entry(
                business_id=self.biz.id,
                entry_type='CAMPAIGN_USAGE_DEBIT',
                amount=-100,  # balance is 0
                reference_id='TX_TEST_FAIL_001',
                description='Should fail',
                actor=self.user
            )
        self.biz.refresh_from_db()
        self.assertEqual(self.biz.credit_balance, 0)

    def test_reservation_and_release(self):
        # Add 100 credits
        CreditLedgerService.record_entry(
            business_id=self.biz.id,
            entry_type='PURCHASE_CREDIT',
            amount=100,
            reference_id='TX_INIT_100',
            description='Initial credits'
        )
        self.biz.refresh_from_db()
        self.assertEqual(self.biz.credit_balance, 100)

        # Hold/Reserve 80 credits for campaign
        CreditLedgerService.record_entry(
            business_id=self.biz.id,
            entry_type='CAMPAIGN_RESERVATION',
            amount=-80,
            reference_id='TX_HOLD_80',
            description='Hold for campaign'
        )
        self.biz.refresh_from_db()
        self.assertEqual(self.biz.credit_balance, 20)

        # Release 30 unused credits back
        CreditLedgerService.record_entry(
            business_id=self.biz.id,
            entry_type='RESERVATION_RELEASE',
            amount=+30,
            reference_id='TX_REL_30',
            description='Release unused'
        )
        self.biz.refresh_from_db()
        self.assertEqual(self.biz.credit_balance, 50)

    @override_settings(PAYSTACK_SECRET_KEY='sk_test_mock_secret', PAYMENT_SANDBOX_MODE=False)
    def test_paystack_webhook_signature_verification(self):
        adapter = PaystackPaymentAdapter()
        body = b'{"event":"charge.success","data":{"reference":"REF123"}}'
        valid_sig = hmac.new(b'sk_test_mock_secret', body, hashlib.sha512).hexdigest()
        self.assertTrue(adapter.verify_webhook_signature(body, valid_sig))
        self.assertFalse(adapter.verify_webhook_signature(body, 'invalid_sig'))

    @override_settings(PAYSTACK_SECRET_KEY='sk_test_mock_secret', PAYMENT_SANDBOX_MODE=False)
    def test_paystack_webhook_processing(self):
        purchase = Purchase.objects.create(
            business=self.biz,
            package=self.pkg,
            credits_granted=500,
            amount_paid=Decimal('35.00'),
            currency='GHS',
            status=Purchase.Status.PENDING,
            payment_reference='PAY_REF_TEST_999'
        )

        client = Client()
        payload = {
            'event': 'charge.success',
            'data': {
                'reference': 'PAY_REF_TEST_999',
                'amount': 3500,
                'currency': 'GHS',
                'fees': 70
            }
        }
        body = json.dumps(payload).encode('utf-8')
        signature = hmac.new(b'sk_test_mock_secret', body, hashlib.sha512).hexdigest()

        # Send webhook
        resp = client.post(
            reverse('billing:paystack_webhook'),
            data=body,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature
        )
        self.assertEqual(resp.status_code, 200)

        # Verify purchase and credits
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.Status.COMPLETED)
        self.biz.refresh_from_db()
        self.assertEqual(self.biz.credit_balance, 500)

        # Re-sending same webhook (duplicate) should not credit twice
        resp_dup = client.post(
            reverse('billing:paystack_webhook'),
            data=body,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature
        )
        self.assertEqual(resp_dup.status_code, 200)
        self.biz.refresh_from_db()
        self.assertEqual(self.biz.credit_balance, 500)

    def test_ledger_csv_export(self):
        BusinessMembership.objects.create(user=self.user, business=self.biz, role='OWNER')
        CreditLedgerService.record_entry(
            business_id=self.biz.id,
            entry_type='PURCHASE_CREDIT',
            amount=500,
            reference_id='TX_EXPORT_001',
            description='Export test credit purchase',
            actor=self.user
        )

        client = Client()
        client.login(username='test@business.com', password='Password123!')
        resp = client.get('/billing/ledger/export/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv; charset=utf-8')
        content = resp.content.decode('utf-8')
        self.assertIn('Reference ID,Entry Type,Amount,Balance After,Description,Purchase Reference,Actor,Timestamp', content)
        self.assertIn('TX_EXPORT_001,PURCHASE_CREDIT,500,500,Export test credit purchase', content)


