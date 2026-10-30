from decimal import Decimal
from django.core.management.base import BaseCommand
from billing.models import SMSPackage


class Command(BaseCommand):
    help = 'Seeds initial default retail SMS packages for Ghana market (GHS)'

    def handle(self, *args, **options):
        packages_data = [
            {
                'name': 'Starter 100',
                'credits': 100,
                'price_ghs': Decimal('8.00'),
                'estimated_provider_cost_ghs': Decimal('3.50'),
                'description': 'Ideal for small clubs or testing out messaging campaigns.',
                'is_promotional': False
            },
            {
                'name': 'Bronze 500',
                'credits': 500,
                'price_ghs': Decimal('35.00'),
                'estimated_provider_cost_ghs': Decimal('17.50'),
                'description': 'Perfect for gyms, tuition centers, and boutique stores.',
                'is_promotional': False
            },
            {
                'name': 'Silver 1,000',
                'credits': 1000,
                'price_ghs': Decimal('65.00'),
                'estimated_provider_cost_ghs': Decimal('35.00'),
                'description': 'Great for community churches and mid-sized retail stores.',
                'is_promotional': True,
                'promo_price_ghs': Decimal('60.00')
            },
            {
                'name': 'Gold 5,000',
                'credits': 5000,
                'price_ghs': Decimal('300.00'),
                'estimated_provider_cost_ghs': Decimal('175.00'),
                'description': 'Best value for high-volume schools and regional organizations.',
                'is_promotional': False
            },
            {
                'name': 'Enterprise 10,000',
                'credits': 10000,
                'price_ghs': Decimal('580.00'),
                'estimated_provider_cost_ghs': Decimal('350.00'),
                'description': 'Maximum volume tier with high wholesale margins.',
                'is_promotional': False
            },
        ]

        created_count = 0
        for pdata in packages_data:
            pkg, created = SMSPackage.objects.get_or_create(
                name=pdata['name'],
                defaults=pdata
            )
            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully seeded {created_count} SMS packages."))
