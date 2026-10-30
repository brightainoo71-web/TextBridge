from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, Business, BusinessMembership


class AccountTenantTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Business 1 (IronFit)
        self.user1 = User.objects.create_user(
            email='gym@example.com',
            password='Password123!',
            first_name='Kofi',
            last_name='Mensah'
        )
        self.biz1 = Business.objects.create(
            name='IronFit Gym',
            category=Business.Category.GYM,
            contact_email='gym@example.com',
            contact_phone='233241234567',
            status=Business.Status.ACTIVE
        )
        BusinessMembership.objects.create(user=self.user1, business=self.biz1, role='OWNER')

        # Business 2 (Apex School)
        self.user2 = User.objects.create_user(
            email='school@example.com',
            password='Password123!',
            first_name='Ama',
            last_name='Serwaa'
        )
        self.biz2 = Business.objects.create(
            name='Apex Academy',
            category=Business.Category.SCHOOL,
            contact_email='school@example.com',
            contact_phone='233201234567',
            status=Business.Status.ACTIVE
        )
        BusinessMembership.objects.create(user=self.user2, business=self.biz2, role='OWNER')

        # Platform Superadmin
        self.admin = User.objects.create_superuser(
            email='admin@platform.com',
            password='AdminPassword123!',
            first_name='Super',
            last_name='Admin'
        )

    def test_business_registration(self):
        resp = self.client.post(reverse('accounts:register'), {
            'business_name': 'New Church Int',
            'business_category': 'CHURCH',
            'preferred_sender_id': 'NEWCHURCH',
            'first_name': 'Pastor',
            'last_name': 'Kwame',
            'email': 'pastor@church.org',
            'phone_number': '0241234567',
            'password': 'SecurePassword123!',
            'password_confirm': 'SecurePassword123!',
        })
        self.assertEqual(resp.status_code, 302)
        biz = Business.objects.filter(name='New Church Int').first()
        self.assertIsNotNone(biz)
        self.assertEqual(biz.preferred_sender_id, 'NEWCHURCH')

    def test_tenant_isolation_redirect(self):
        # Unauthenticated user trying to access contacts should be redirected to login
        resp = self.client.get(reverse('contacts:contact_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/auth/login/', resp.url)

    def test_superadmin_access_control(self):
        # Ordinary user cannot access admin dashboard
        self.client.login(username='gym@example.com', password='Password123!')
        resp = self.client.get(reverse('analytics:admin_dashboard'))
        # Should be redirected
        self.assertEqual(resp.status_code, 302)

        # Superadmin can access
        self.client.logout()
        self.client.login(username='admin@platform.com', password='AdminPassword123!')
        resp = self.client.get(reverse('analytics:admin_dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_suspended_business_block(self):
        self.biz1.status = Business.Status.SUSPENDED
        self.biz1.save()

        self.client.login(username='gym@example.com', password='Password123!')
        resp = self.client.get(reverse('contacts:contact_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/auth/suspended/', resp.url)
