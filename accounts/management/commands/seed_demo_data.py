from decimal import Decimal
from django.core.management.base import BaseCommand
from accounts.models import User, Business, BusinessMembership, AuditLog
from contacts.models import Contact, ContactGroup, ContactGroupMembership, SuppressionRecord
from billing.models import SMSPackage, Purchase
from billing.ledger_service import CreditLedgerService
from messaging.models import SenderID, SMSCampaign


class Command(BaseCommand):
    help = 'Seeds superadmin, sample demo businesses (Gym, School, Church), contacts, and credits for testing.'

    def handle(self, *args, **options):
        # 1. Superadmin User
        admin_email = 'admin@brightsms.com'
        admin_pass = 'Admin12345!'
        admin_user, created = User.objects.get_or_create(
            email=admin_email,
            defaults={
                'first_name': 'Platform',
                'last_name': 'Administrator',
                'role': User.Role.SUPERADMIN,
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if created:
            admin_user.set_password(admin_pass)
            admin_user.save()
            self.stdout.write(self.style.SUCCESS(f"Created Superadmin: {admin_email} / {admin_pass}"))
        else:
            self.stdout.write(f"Superadmin {admin_email} already exists.")

        # 2. Demo Business: IronFit Gym
        gym_user_email = 'owner@ironfitgym.com'
        gym_user_pass = 'GymOwner123!'
        gym_user, created = User.objects.get_or_create(
            email=gym_user_email,
            defaults={
                'first_name': 'Kofi',
                'last_name': 'Mensah',
                'phone_number': '233241234567',
                'role': User.Role.BUSINESS_USER
            }
        )
        if created:
            gym_user.set_password(gym_user_pass)
            gym_user.save()

        gym_biz, created = Business.objects.get_or_create(
            name='IronFit Gym & Wellness',
            defaults={
                'category': Business.Category.GYM,
                'contact_email': gym_user_email,
                'contact_phone': '233241234567',
                'address': 'Plot 4, Spintex Road',
                'city': 'Accra',
                'preferred_sender_id': 'IRONFIT',
                'status': Business.Status.ACTIVE
            }
        )

        BusinessMembership.objects.get_or_create(
            user=gym_user,
            business=gym_biz,
            defaults={'role': BusinessMembership.Role.OWNER}
        )

        SenderID.objects.get_or_create(
            business=gym_biz,
            sender_id='IRONFIT',
            defaults={
                'purpose': 'Workout schedule updates and subscription reminders',
                'status': SenderID.Status.APPROVED
            }
        )

        # Give Gym 500 initial demo credits if balance is 0
        if gym_biz.credit_balance == 0:
            CreditLedgerService.record_entry(
                business_id=gym_biz.id,
                entry_type='ADMIN_ADJUSTMENT',
                amount=500,
                reference_id='SEED_INIT_CREDITS_GYM',
                description='Initial complimentary onboarding credits',
                actor=admin_user
            )

        # Create Contact Groups for Gym
        vip_group, _ = ContactGroup.objects.get_or_create(
            business=gym_biz,
            name='VIP Members',
            defaults={'description': 'Premium personal trainer clients'}
        )
        general_group, _ = ContactGroup.objects.get_or_create(
            business=gym_biz,
            name='All Gym Members',
            defaults={'description': 'Active members on standard monthly pass'}
        )

        # Seed Synthetic Contacts
        demo_contacts = [
            ('Ama Serwaa', '233241112233', 'ama@example.com', [vip_group, general_group]),
            ('Kwame Asante', '233201234567', 'kwame@example.com', [general_group]),
            ('Abena Osei', '233549988776', 'abena@example.com', [general_group]),
            ('Yaw Boateng', '233271122334', 'yaw@example.com', [vip_group]),
            ('Akosua Mensah', '233501239874', 'akosua@example.com', [general_group]),
        ]

        for name, phone, email, groups in demo_contacts:
            c, _ = Contact.objects.get_or_create(
                business=gym_biz,
                phone_number=phone,
                defaults={'name': name, 'email': email, 'is_subscribed': True}
            )
            for g in groups:
                ContactGroupMembership.objects.get_or_create(contact=c, group=g)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded Demo Business: '{gym_biz.name}' (User: {gym_user_email} / {gym_user_pass})"
        ))
