import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from messaging.campaign_service import CampaignService


class Command(BaseCommand):
    help = "Dispatches scheduled SMS campaigns whose dispatch timestamp has arrived."

    def add_arguments(self, parser):
        parser.add_argument(
            '--loop',
            action='store_true',
            help='Run continuously in a loop polling for due campaigns',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=30,
            help='Polling interval in seconds when running in --loop mode (default: 30s)',
        )

    def handle(self, *args, **options):
        is_loop = options.get('loop', False)
        interval = options.get('interval', 30)

        if is_loop:
            self.stdout.write(self.style.SUCCESS(
                f"[*] Starting TextBridge Scheduled Campaign Dispatcher (polling every {interval}s). Press CTRL+C to exit."
            ))
            while True:
                try:
                    self._run_dispatch_cycle()
                    time.sleep(interval)
                except KeyboardInterrupt:
                    self.stdout.write(self.style.WARNING("\n[!] Stopping scheduled campaign dispatcher."))
                    break
        else:
            self._run_dispatch_cycle()

    def _run_dispatch_cycle(self):
        summary = CampaignService.process_due_scheduled_campaigns()
        if summary['due_count'] > 0:
            self.stdout.write(self.style.SUCCESS(
                f"[{timezone.now():%Y-%m-%d %H:%M:%S}] Found {summary['due_count']} due campaign(s). "
                f"Successfully dispatched: {summary['dispatched_count']}, Failed: {summary['failed_count']}."
            ))
            if summary['errors']:
                for err in summary['errors']:
                    self.stdout.write(self.style.ERROR(f"  - Error: {err}"))
        else:
            self.stdout.write(f"[{timezone.now():%H:%M:%S}] No scheduled campaigns are due for dispatch.")
