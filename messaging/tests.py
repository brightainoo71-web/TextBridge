from decimal import Decimal
from django.test import TestCase, override_settings
from accounts.models import User, Business
from contacts.models import Contact, ContactGroup, ContactGroupMembership, SuppressionRecord
from billing.ledger_service import CreditLedgerService
from messaging.models import SMSCampaign, CampaignRecipient
from messaging.segmentation import calculate_sms_segments
from messaging.providers import MockSMSProvider
from messaging.campaign_service import CampaignService


@override_settings(ACTIVE_SMS_PROVIDER='MOCK')
class MessagingCampaignTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='biz@test.com', password='Password123!')
        self.biz = Business.objects.create(name='Test Biz', contact_email='biz@test.com', credit_balance=0)

        # Give 200 credits
        CreditLedgerService.record_entry(
            business_id=self.biz.id,
            entry_type='PURCHASE_CREDIT',
            amount=200,
            reference_id='INIT_CREDITS_200',
            description='Test balance'
        )
        self.biz.refresh_from_db()

        # Create contacts
        self.contact1 = Contact.objects.create(business=self.biz, name='Ama Mensah', phone_number='233241111111')
        self.contact2 = Contact.objects.create(business=self.biz, name='Kwame Boateng', phone_number='233202222222')
        # Suppressed contact
        self.contact_suppressed = Contact.objects.create(business=self.biz, name='Opted Out User', phone_number='233543333333')
        SuppressionRecord.objects.create(business=self.biz, phone_number='233543333333', reason='OPT_OUT')

    def test_sms_segmentation_gsm(self):
        # 160 GSM chars = 1 segment
        msg_160 = "A" * 160
        res = calculate_sms_segments(msg_160)
        self.assertFalse(res['is_unicode'])
        self.assertEqual(res['segment_count'], 1)

        # 161 GSM chars = 2 segments
        msg_161 = "A" * 161
        res = calculate_sms_segments(msg_161)
        self.assertFalse(res['is_unicode'])
        self.assertEqual(res['segment_count'], 2)

    def test_sms_segmentation_unicode(self):
        # Message with emoji or non-GSM character switches to UCS-2 (70 chars per segment)
        msg_unicode = "Welcome to our Gym! 🏋️‍♂️"
        res = calculate_sms_segments(msg_unicode)
        self.assertTrue(res['is_unicode'])
        self.assertEqual(res['segment_count'], 1)

        long_unicode = "🏋️" * 36  # Each emoji is multiple code units
        res2 = calculate_sms_segments(long_unicode)
        self.assertTrue(res2['is_unicode'])
        self.assertGreater(res2['segment_count'], 1)

    def test_mock_sms_provider(self):
        provider = MockSMSProvider()
        # Standard valid number
        res = provider.send_single("POWERGYM", "233241234567", "Hello world")
        self.assertTrue(res.is_success)
        self.assertEqual(res.status, 'DELIVERED')

        # Number ending in 0000 simulates failure
        res_fail = provider.send_single("POWERGYM", "233241230000", "Hello world")
        self.assertFalse(res_fail.is_success)
        self.assertEqual(res_fail.status, 'FAILED')

    def test_campaign_dispatch_and_suppression(self):
        campaign = SMSCampaign.objects.create(
            business=self.biz,
            title='Test Broadcast',
            sender_id='TESTBIZ',
            message_template='Hi {{name}}, workout starts at 6pm!'
        )

        prep = CampaignService.prepare_recipients(campaign)
        # Should have prepared 2 valid recipients, suppressing 1
        self.assertEqual(prep['valid_recipients'], 2)
        self.assertEqual(prep['suppressed_recipients'], 1)

        # Check personalized message rendered
        r1 = campaign.recipients.filter(phone_number='233241111111').first()
        self.assertEqual(r1.rendered_message, 'Hi Ama Mensah, workout starts at 6pm!')

        # Dispatch
        dispatch_res = CampaignService.dispatch_campaign(campaign, actor=self.user)
        self.assertEqual(dispatch_res['delivered_count'], 2)
        self.assertEqual(dispatch_res['failed_count'], 0)
        self.assertEqual(campaign.status, SMSCampaign.Status.COMPLETED)

        # Verify balance deducted: 200 - 2 = 198
        self.biz.refresh_from_db()
        self.assertEqual(self.biz.credit_balance, 198)

    def test_dlr_webhook_ping_get(self):
        resp = self.client.get('/messaging/webhook/mnotify/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'active')

    def test_dlr_webhook_updates_campaign_recipient(self):
        from messaging.models import SMSMessage
        campaign = SMSCampaign.objects.create(
            business=self.biz,
            title='DLR Campaign',
            sender_id='TESTBIZ',
            status=SMSCampaign.Status.PROCESSING
        )
        recip = CampaignRecipient.objects.create(
            campaign=campaign,
            phone_number='233241111111',
            rendered_message='Test DLR',
            status=CampaignRecipient.Status.ACCEPTED,
            provider_message_id='MNOTIFY_MSG_12345'
        )

        # Send DLR POST
        resp = self.client.post(
            '/messaging/webhook/mnotify/',
            data='{"message_id": "MNOTIFY_MSG_12345", "status": "DELIVERED"}',
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['updated_records'], 1)

        recip.refresh_from_db()
        self.assertEqual(recip.status, CampaignRecipient.Status.DELIVERED)

        campaign.refresh_from_db()
        self.assertEqual(campaign.status, SMSCampaign.Status.COMPLETED)

    def test_dlr_webhook_updates_direct_sms(self):
        from messaging.models import SMSMessage
        msg = SMSMessage.objects.create(
            business=self.biz,
            recipient_phone='233241111111',
            sender_id='TESTBIZ',
            message='Test direct SMS',
            status=SMSMessage.Status.QUEUED,
            provider_message_id='MNOTIFY_DIR_999'
        )

        resp = self.client.post(
            '/messaging/webhook/mnotify/',
            data='{"message_id": "MNOTIFY_DIR_999", "status": "FAILED", "reason": "Absent subscriber"}',
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['updated_records'], 1)

        msg.refresh_from_db()
        self.assertEqual(msg.status, SMSMessage.Status.FAILED)
