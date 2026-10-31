import logging
from django.utils import timezone
from contacts.birthday_service import BirthdayAutomationService

logger = logging.getLogger('textbridge.birthdays')

try:
    from celery import shared_task
    HAVE_CELERY = True
except ImportError:
    HAVE_CELERY = False

if HAVE_CELERY:
    @shared_task(name='contacts.tasks.dispatch_daily_birthdays_task')
    def dispatch_daily_birthdays_task():
        """
        Automated Celery Beat job that evaluates and dispatches birthday greetings
        daily across all active tenant accounts in TextBridge.
        """
        today = timezone.localdate()
        logger.info(f"[Celery Beat] Executing automated daily birthday greetings check for {today}...")
        try:
            stats = BirthdayAutomationService.dispatch_daily_birthdays(today=today)
            logger.info(
                f"[Celery Beat] Birthday dispatch completed for {today}. "
                f"Businesses: {stats['businesses_processed']}, "
                f"Sent: {stats['sent_count']}, "
                f"Skipped: {stats['skipped_count']}, "
                f"Failed: {stats['failed_count']}"
            )
            return stats
        except Exception as exc:
            logger.error(f"[Celery Beat] Error in dispatch_daily_birthdays_task: {exc}", exc_info=True)
            return {'status': 'ERROR', 'error': str(exc)}
