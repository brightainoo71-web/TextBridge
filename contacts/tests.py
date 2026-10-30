import io
from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from accounts.models import User, Business, BusinessMembership
from contacts.models import Contact, ContactGroup, ContactGroupMembership, SuppressionRecord
from contacts.utils import normalize_phone_number
from contacts.importer import ContactImporter


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
