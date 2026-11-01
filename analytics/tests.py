from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, Business, BusinessMembership
from messaging.models import SenderID


class AdminSenderIDManagementTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Superadmin user
        self.superadmin = User.objects.create_superuser(
            email='admin@textbridge.test',
            password='AdminPassword123!',
            first_name='Platform',
            last_name='Admin'
        )

        # Tenant business & user
        self.tenant_user = User.objects.create_user(
            email='gym@ironfit.test',
            password='Password123!',
            first_name='Gym',
            last_name='Owner',
            role=User.Role.BUSINESS_USER
        )
        self.business = Business.objects.create(
            name='IronFit Gym',
            category=Business.Category.GYM,
            contact_email='gym@ironfit.test',
            status=Business.Status.ACTIVE
        )
        BusinessMembership.objects.create(
            user=self.tenant_user,
            business=self.business,
            role=BusinessMembership.Role.OWNER
        )

    def test_admin_sender_id_list_requires_superadmin(self):
        # Unauthenticated
        response = self.client.get(reverse('analytics:admin_sender_ids'))
        self.assertEqual(response.status_code, 302)

        # Tenant user access blocked
        self.client.login(email='gym@ironfit.test', password='Password123!')
        response = self.client.get(reverse('analytics:admin_sender_ids'))
        self.assertEqual(response.status_code, 302)

        # Superadmin access allowed
        self.client.login(email='admin@textbridge.test', password='AdminPassword123!')
        response = self.client.get(reverse('analytics:admin_sender_ids'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Platform Sender ID Management')

    def test_superadmin_can_provision_sender_id_for_business(self):
        self.client.login(email='admin@textbridge.test', password='AdminPassword123!')
        response = self.client.post(reverse('analytics:admin_sender_ids'), {
            'action': 'create',
            'business_id': self.business.id,
            'sender_id': 'IRONFIT',
            'purpose': 'Member workout alerts and renewals',
            'status': SenderID.Status.APPROVED
        })
        self.assertEqual(response.status_code, 302)

        sid = SenderID.objects.filter(sender_id='IRONFIT', business=self.business).first()
        self.assertIsNotNone(sid)
        self.assertEqual(sid.status, SenderID.Status.APPROVED)
        self.assertFalse(sid.is_system_default)

        # Check business preferred_sender_id updated
        self.business.refresh_from_db()
        self.assertEqual(self.business.preferred_sender_id, 'IRONFIT')

    def test_superadmin_can_create_system_default_sender_id(self):
        self.client.login(email='admin@textbridge.test', password='AdminPassword123!')
        response = self.client.post(reverse('analytics:admin_sender_ids'), {
            'action': 'create',
            'is_system_default': '1',
            'sender_id': 'TEXTBRIDGE',
            'purpose': 'Platform-wide instant default sender ID',
            'status': SenderID.Status.APPROVED
        })
        self.assertEqual(response.status_code, 302)

        sid = SenderID.objects.filter(sender_id='TEXTBRIDGE', is_system_default=True).first()
        self.assertIsNotNone(sid)
        self.assertIsNone(sid.business)
        self.assertTrue(sid.is_system_default)

    def test_superadmin_can_approve_pending_sender_id(self):
        # Create pending Sender ID
        pending_sid = SenderID.objects.create(
            business=self.business,
            sender_id='FITNESSGH',
            purpose='Fitness announcements',
            status=SenderID.Status.PENDING
        )

        self.client.login(email='admin@textbridge.test', password='AdminPassword123!')
        response = self.client.post(reverse('analytics:admin_sender_ids'), {
            'action': 'approve',
            'sender_id_id': pending_sid.id
        })
        self.assertEqual(response.status_code, 302)

        pending_sid.refresh_from_db()
        self.assertEqual(pending_sid.status, SenderID.Status.APPROVED)
        self.assertIsNotNone(pending_sid.approved_at)

    def test_superadmin_can_reject_sender_id(self):
        pending_sid = SenderID.objects.create(
            business=self.business,
            sender_id='SPAMMER',
            purpose='Unknown',
            status=SenderID.Status.PENDING
        )

        self.client.login(email='admin@textbridge.test', password='AdminPassword123!')
        response = self.client.post(reverse('analytics:admin_sender_ids'), {
            'action': 'reject',
            'sender_id_id': pending_sid.id,
            'reason': 'Violates Ghana telecom compliance'
        })
        self.assertEqual(response.status_code, 302)

        pending_sid.refresh_from_db()
        self.assertEqual(pending_sid.status, SenderID.Status.REJECTED)
        self.assertEqual(pending_sid.rejection_reason, 'Violates Ghana telecom compliance')

    def test_business_action_add_sender_id(self):
        self.client.login(email='admin@textbridge.test', password='AdminPassword123!')
        response = self.client.post(reverse('analytics:admin_business_action', kwargs={'pk': self.business.id}), {
            'action': 'add_sender_id',
            'sender_id': 'IRONPRO',
            'purpose': 'Assigned by admin',
            'status': SenderID.Status.APPROVED
        })
        self.assertEqual(response.status_code, 302)

        sid = SenderID.objects.filter(sender_id='IRONPRO', business=self.business).first()
        self.assertIsNotNone(sid)
        self.assertEqual(sid.status, SenderID.Status.APPROVED)
