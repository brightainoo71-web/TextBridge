import io
from django.test import TestCase, Client, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from datetime import date, timedelta
from django.utils import timezone
from accounts.models import User, Business, BusinessMembership
from contacts.models import Contact, ContactGroup, ContactGroupMembership, SuppressionRecord, BirthdayAutomation
from contacts.utils import normalize_phone_number
from contacts.importer import ContactImporter
from contacts.birthday_service import BirthdayAutomationService
from billing.ledger_service import CreditLedgerService
from messaging.models import SMSMessage


@override_settings(ACTIVE_SMS_PROVIDER='MOCK')
class ContactsAndImportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='gym@example.com', password='Password123!')
        self.biz = Business.objects.create(name='IronFit Gym', category=Business.Category.GYM, contact_email='gym@example.com')
        BusinessMembership.objects.create(user=self.user, business=self.biz, role='OWNER')

        # Other business to test cross-tenant isolation
        self.other_biz = Business.objects.create(name='Other Shop', category=Business.Category.RETAIL, contact_email='shop@example.com')

    def test_phone_normalization_ghana(self):
        # Local 024 format -> 23324...
        valid, phone, _ = normalize_phone_number('0241234567')
        self.assertTrue(valid)
        self.assertEqual(phone, '233241234567')

        # Leading +233
        valid, phone, _ = normalize_phone_number('+233201234567')
        self.assertTrue(valid)
        self.assertEqual(phone, '233201234567')

        # Telecel (050)
        valid, phone, _ = normalize_phone_number('0509876543')
        self.assertTrue(valid)
        self.assertEqual(phone, '233509876543')

        # Invalid prefix (011 is not a Ghanaian telecom network)
        valid, _, err = normalize_phone_number('0111234567')
        self.assertFalse(valid)
        self.assertIn("Invalid Ghanaian network prefix", err)

        # Invalid length
        valid, _, _ = normalize_phone_number('123')
        self.assertFalse(valid)

    def test_csv_importer(self):
        csv_data = (
            "Name,Phone,Email\n"
            "Kofi Mensah,0241234567,kofi@example.com\n"
            "Ama Serwaa,0209876543,ama@example.com\n"
            "Bad Number,0111234567,bad@example.com\n"
            "Duplicate Kofi,0241234567,kofi2@example.com\n"
        ).encode('utf-8')

        file_obj = SimpleUploadedFile("test_contacts.csv", csv_data, content_type="text/csv")
        importer = ContactImporter(business=self.biz, duplicate_policy='SKIP')
        results = importer.process_import(file_obj, name_col_idx=0, phone_col_idx=1, email_col_idx=2)

        self.assertEqual(results['created_count'], 2)
        self.assertEqual(results['invalid_count'], 1)  # Bad number 011...
        self.assertEqual(results['skipped_count'], 1)  # Duplicate phone 0241234567

        # Verify contacts belong strictly to self.biz
        self.assertEqual(Contact.objects.filter(business=self.biz).count(), 2)
        self.assertEqual(Contact.objects.filter(business=self.other_biz).count(), 0)

    def test_cross_tenant_isolation(self):
        # Create contact in other_biz
        Contact.objects.create(business=self.other_biz, name="Other Contact", phone_number="233240001122")

        client = Client()
        client.login(username='gym@example.com', password='Password123!')
        resp = client.get('/contacts/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Other Contact")

    def test_contact_csv_export(self):
        Contact.objects.create(
            business=self.biz,
            name="Kwame Mensah",
            phone_number="233241112233",
            email="kwame@example.com",
            birth_date=date(1995, 10, 31)
        )
        Contact.objects.create(
            business=self.other_biz,
            name="Other Contact",
            phone_number="233249998877"
        )

        client = Client()
        client.login(username='gym@example.com', password='Password123!')
        resp = client.get('/contacts/export/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv; charset=utf-8')
        content = resp.content.decode('utf-8')
        self.assertIn("Full Name,Phone Number,Email,Birth Date,Subscription Status,Groups,Date Added", content)
        self.assertIn("Kwame Mensah,233241112233,kwame@example.com,1995-10-31,Subscribed", content)
        self.assertNotIn("Other Contact", content)

    def test_birthday_automation_service(self):
        today = timezone.localdate()
        # Allocate 100 credits to self.biz
        CreditLedgerService.record_entry(
            business_id=self.biz.id,
            entry_type='PURCHASE_CREDIT',
            amount=100,
            reference_id='INIT_CREDITS_BDAY_TEST',
            description='Initial test credits'
        )

        # Create contacts: 1 matching birthday, 1 different day, 1 suppressed
        birthday_contact = Contact.objects.create(
            business=self.biz,
            name="Ama Serwaa",
            phone_number="233201112233",
            birth_date=date(1998, today.month, today.day)
        )
        non_bday_contact = Contact.objects.create(
            business=self.biz,
            name="Kofi Annan",
            phone_number="233202223344",
            birth_date=date(1990, (today.month % 12) + 1, 1)
        )
        suppressed_bday = Contact.objects.create(
            business=self.biz,
            name="Opted Out",
            phone_number="233203334455",
            birth_date=date(1992, today.month, today.day)
        )
        SuppressionRecord.objects.create(
            business=self.biz,
            phone_number="233203334455",
            reason='REQUESTED'
        )

        # Configure automation
        BirthdayAutomation.objects.create(
            business=self.biz,
            is_enabled=True,
            sender_id='IronFit',
            message_template="Happy Birthday {{first_name}}! Greetings from {{business_name}}."
        )

        # Run automation
        stats = BirthdayAutomationService.dispatch_daily_birthdays(today=today, business_id=self.biz.id)
        self.assertEqual(stats['birthdays_found'], 2)  # 2 had today's birth month/day
        self.assertEqual(stats['sent_count'], 1)       # 1 successfully sent
        self.assertEqual(stats['skipped_count'], 1)    # 1 skipped due to suppression

        # Verify SMSMessage created
        msg = SMSMessage.objects.filter(business=self.biz, recipient_phone="233201112233").first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.message, "Happy Birthday Ama! Greetings from IronFit Gym.")

        # Test idempotency (running again on same day skips without double charging)
        stats_rerun = BirthdayAutomationService.dispatch_daily_birthdays(today=today, business_id=self.biz.id)
        self.assertEqual(stats_rerun['sent_count'], 0)
        self.assertEqual(stats_rerun['skipped_count'], 2)

    def test_birthday_automation_ui(self):
        client = Client()
        client.login(username='gym@example.com', password='Password123!')

        # GET config page
        resp = client.get('/contacts/birthdays/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Automated Birthday Greetings")

        # POST save config
        resp = client.post('/contacts/birthdays/', {
            'is_enabled': 'on',
            'sender_id': 'IronFit',
            'dispatch_time': '09:00:00',
            'message_template': 'Happy Birthday {{first_name}}!'
        })
        self.assertEqual(resp.status_code, 302)
        auto = BirthdayAutomation.objects.get(business=self.biz)
        self.assertTrue(auto.is_enabled)
        self.assertEqual(auto.sender_id, 'IronFit')

