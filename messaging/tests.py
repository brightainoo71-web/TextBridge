import json
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from django.test import TestCase, override_settings
from accounts.models import User, Business, APIKey, BusinessMembership
from contacts.models import Contact, ContactGroup, ContactGroupMembership, SuppressionRecord
from billing.ledger_service import CreditLedgerService
from messaging.models import SMSCampaign, CampaignRecipient, SenderID, SMSMessage
from messaging.forms import CampaignComposeForm
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


@override_settings(ACTIVE_SMS_PROVIDER='MOCK')
class DeveloperApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='developer@test.com', password='Password123!')
        self.biz = Business.objects.create(name='Dev Startup', contact_email='developer@test.com', credit_balance=50)
        self.api_key_obj, self.raw_key = APIKey.generate(self.biz, name="Production Bot Key")

        # Approved sender IDs
        self.default_sid = SenderID.objects.create(
            sender_id='TextBridge',
            status=SenderID.Status.APPROVED,
            is_system_default=True
        )
        self.custom_sid = SenderID.objects.create(
            business=self.biz,
            sender_id='DEVSTARTUP',
            status=SenderID.Status.APPROVED
        )

    def test_missing_api_key_returns_401(self):
        resp = self.client.get('/api/v1/balance')
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()['error'], 'Unauthorized')

    def test_invalid_api_key_returns_401(self):
        resp = self.client.get('/api/v1/balance', HTTP_AUTHORIZATION='Bearer tb_live_invalidkey12345')
        self.assertEqual(resp.status_code, 401)

    def test_balance_endpoint_with_valid_bearer_token(self):
        resp = self.client.get('/api/v1/balance', HTTP_AUTHORIZATION=f'Bearer {self.raw_key}')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['credit_balance'], 50)
        self.assertEqual(data['business_name'], 'Dev Startup')

    def test_balance_endpoint_with_x_api_key_header(self):
        resp = self.client.get('/api/v1/balance', HTTP_X_API_KEY=self.raw_key)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['credit_balance'], 50)

    def test_send_sms_valid_dispatches_and_deducts(self):
        payload = {
            'recipient': '0241112233',
            'message': 'Your verification OTP is 493021',
            'sender_id': 'DEVSTARTUP'
        }
        resp = self.client.post(
            '/api/v1/sms/send',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.raw_key}'
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['recipient'], '233241112233')
        self.assertEqual(data['sender_id'], 'DEVSTARTUP')
        self.assertEqual(data['credits_deducted'], 1)
        self.assertEqual(data['remaining_balance'], 49)

        # Check database balance
        self.biz.refresh_from_db()
        self.assertEqual(self.biz.credit_balance, 49)

    def test_send_sms_unapproved_sender_id_returns_403(self):
        payload = {
            'recipient': '0241112233',
            'message': 'Testing unapproved sender',
            'sender_id': 'STOLENID'
        }
        resp = self.client.post(
            '/api/v1/sms/send',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.raw_key}'
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['error'], 'Forbidden')

    def test_send_sms_insufficient_balance_returns_402(self):
        self.biz.credit_balance = 0
        self.biz.save()

        payload = {
            'recipient': '0241112233',
            'message': 'Should fail due to zero balance',
        }
        resp = self.client.post(
            '/api/v1/sms/send',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.raw_key}'
        )
        self.assertEqual(resp.status_code, 402)
        self.assertEqual(resp.json()['error'], 'Payment Required')

    def test_revoked_api_key_returns_401(self):
        self.api_key_obj.is_active = False
        self.api_key_obj.save()

        resp = self.client.get('/api/v1/balance', HTTP_AUTHORIZATION=f'Bearer {self.raw_key}')
        self.assertEqual(resp.status_code, 401)


@override_settings(ACTIVE_SMS_PROVIDER='MOCK')
class ScheduledCampaignTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='scheduler@test.com', password='Password123!')
        self.biz = Business.objects.create(name='Schedule Biz', contact_email='scheduler@test.com', credit_balance=50)
        BusinessMembership.objects.create(user=self.user, business=self.biz, role=BusinessMembership.Role.OWNER)

        self.sid = SenderID.objects.create(
            sender_id='SCHEDULEBIZ',
            status=SenderID.Status.APPROVED,
            business=self.biz
        )
        self.contact1 = Contact.objects.create(business=self.biz, name='Adwoa Doe', phone_number='233241234567')

    def test_scheduling_in_past_is_invalid(self):
        form_data = {
            'title': 'Past Broadcast',
            'sender_id': 'SCHEDULEBIZ',
            'message_template': 'Hello {{name}}',
            'is_scheduled': True,
            'scheduled_at': (timezone.now() - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M')
        }
        form = CampaignComposeForm(data=form_data, business=self.biz)
        self.assertFalse(form.is_valid())
        self.assertIn('scheduled_at', form.errors)

    def test_scheduling_in_future_creates_scheduled_campaign(self):
        future_time = timezone.now() + timedelta(days=2)
        form_data = {
            'title': 'Future Promo',
            'sender_id': 'SCHEDULEBIZ',
            'message_template': 'Promo for {{name}}!',
            'is_scheduled': True,
            'scheduled_at': future_time.strftime('%Y-%m-%dT%H:%M')
        }
        form = CampaignComposeForm(data=form_data, business=self.biz)
        self.assertTrue(form.is_valid(), form.errors)

        self.client.force_login(self.user)
        session = self.client.session
        session['active_business_id'] = self.biz.id
        session.save()

        resp = self.client.post('/messaging/campaigns/new/', data=form_data)
        self.assertEqual(resp.status_code, 302)

        campaign = SMSCampaign.objects.get(title='Future Promo')
        self.assertEqual(campaign.status, SMSCampaign.Status.SCHEDULED)
        self.assertTrue(campaign.is_scheduled)
        self.assertIsNotNone(campaign.scheduled_at)

    def test_cancel_scheduled_campaign(self):
        future_time = timezone.now() + timedelta(days=1)
        campaign = SMSCampaign.objects.create(
            business=self.biz,
            title='To Cancel',
            sender_id='SCHEDULEBIZ',
            message_template='Test',
            is_scheduled=True,
            scheduled_at=future_time,
            status=SMSCampaign.Status.SCHEDULED
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['active_business_id'] = self.biz.id
        session.save()

        resp = self.client.post(f'/messaging/campaigns/{campaign.id}/cancel/')
        self.assertEqual(resp.status_code, 302)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, SMSCampaign.Status.CANCELLED)

    def test_process_due_scheduled_campaigns(self):
        due_campaign = SMSCampaign.objects.create(
            business=self.biz,
            title='Due Campaign',
            sender_id='SCHEDULEBIZ',
            message_template='Hello {{name}}',
            is_scheduled=True,
            scheduled_at=timezone.now() - timedelta(minutes=5),
            status=SMSCampaign.Status.SCHEDULED
        )

        future_campaign = SMSCampaign.objects.create(
            business=self.biz,
            title='Future Campaign',
            sender_id='SCHEDULEBIZ',
            message_template='Hello {{name}}',
            is_scheduled=True,
            scheduled_at=timezone.now() + timedelta(hours=2),
            status=SMSCampaign.Status.SCHEDULED
        )

        summary = CampaignService.process_due_scheduled_campaigns()
        self.assertEqual(summary['due_count'], 1)
        self.assertEqual(summary['dispatched_count'], 1)

        due_campaign.refresh_from_db()
        self.assertEqual(due_campaign.status, SMSCampaign.Status.COMPLETED)
        self.assertEqual(due_campaign.actual_credits_used, 1)

        future_campaign.refresh_from_db()
        self.assertEqual(future_campaign.status, SMSCampaign.Status.SCHEDULED)

    def test_process_due_campaign_fails_on_insufficient_credits(self):
        self.biz.credit_balance = 0
        self.biz.save()

        due_campaign = SMSCampaign.objects.create(
            business=self.biz,
            title='No Credits Due Campaign',
            sender_id='SCHEDULEBIZ',
            message_template='Hello {{name}}',
            is_scheduled=True,
            scheduled_at=timezone.now() - timedelta(minutes=2),
            status=SMSCampaign.Status.SCHEDULED
        )

        summary = CampaignService.process_due_scheduled_campaigns()
        self.assertEqual(summary['due_count'], 1)
        self.assertEqual(summary['failed_count'], 1)

        due_campaign.refresh_from_db()
        self.assertEqual(due_campaign.status, SMSCampaign.Status.FAILED)


