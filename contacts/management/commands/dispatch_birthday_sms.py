from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from contacts.birthday_service import BirthdayAutomationService


class Command(BaseCommand):
    help = "Dispatches automated Birthday SMS greetings to contacts celebrating today."

    def add_arguments(self, parser):
        parser.add_argument(
            '--business-id',
            type=int,
            help='Run automation strictly for a single business ID',
        )
        parser.add_argument(
            '--date',
            type=str,
            help='Simulate a specific date (YYYY-MM-DD) for birthday matching',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate birthday checks and message rendering without debiting credits or sending SMS',
        )

    def handle(self, *args, **options):
        business_id = options.get('business_id')
        date_str = options.get('date')
        dry_run = options.get('dry_run', False)

        target_date = timezone.localdate()
        if date_str:
            try:
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                self.stderr.write(self.style.ERROR(f"Invalid date format: {date_str}. Use YYYY-MM-DD."))
                return

        mode_str = "[DRY-RUN] " if dry_run else ""
        self.stdout.write(self.style.NOTICE(f"{mode_str}Running Birthday SMS Automation for {target_date}..."))

        stats = BirthdayAutomationService.dispatch_daily_birthdays(
            today=target_date,
            business_id=business_id,
            dry_run=dry_run
        )

        self.stdout.write(self.style.SUCCESS(
            f"Done! Businesses: {stats['businesses_processed']}, "
            f"Birthdays Found: {stats['birthdays_found']}, "
            f"Sent: {stats['sent_count']}, "
            f"Skipped: {stats['skipped_count']}, "
            f"Failed: {stats['failed_count']}, "
            f"Insufficient Credits: {stats['insufficient_credits_count']}, "
            f"Credits Spent: {stats['credits_spent']}"
        ))

        for detail in stats['details']:
            self.stdout.write(f" - [{detail['status']}] {detail['business']} -> {detail['contact']} ({detail['phone']})")
