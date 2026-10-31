import logging
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from accounts.models import Business
from billing.ledger_service import CreditLedgerService, InsufficientCreditsError, DuplicateTransactionError
from messaging.segmentation import calculate_sms_segments
from messaging.providers import get_sms_provider
from messaging.models import SMSMessage
from contacts.models import Contact, BirthdayAutomation, SuppressionRecord

logger = logging.getLogger('textbridge.birthdays')


class BirthdayAutomationService:
    @staticmethod
    def render_message(template: str, contact_name: str, business_name: str) -> str:
        name = contact_name.strip() if contact_name else "Valued Customer"
        first_name = name.split()[0] if name else "Valued Customer"

        rendered = template or "Happy Birthday {{first_name}}! Wishing you joy and prosperity from {{business_name}}."
        rendered = rendered.replace('{{first_name}}', first_name)
        rendered = rendered.replace('{{name}}', name)
        rendered = rendered.replace('{{business_name}}', business_name or 'TextBridge')
        return rendered

    @classmethod
    def get_upcoming_birthdays(cls, business: Business, days: int = 14) -> list:
        """
        Returns contacts having birthdays in the upcoming `days` window (including today).
        """
        today = timezone.localdate()
        active_contacts = Contact.objects.filter(
            business=business,
            is_subscribed=True,
            birth_date__isnull=False
        )

        upcoming = []
        for contact in active_contacts:
            bdate = contact.birth_date
            # Determine birthday this year
            try:
                this_year_bday = bdate.replace(year=today.year)
            except ValueError:
                # Handle Feb 29 on non-leap years
                this_year_bday = bdate.replace(year=today.year, month=3, day=1)

            if this_year_bday < today:
                try:
                    next_bday = bdate.replace(year=today.year + 1)
                except ValueError:
                    next_bday = bdate.replace(year=today.year + 1, month=3, day=1)
            else:
                next_bday = this_year_bday

            delta_days = (next_bday - today).days
            if 0 <= delta_days <= days:
                turning_age = next_bday.year - bdate.year if bdate.year > 1900 else None
                upcoming.append({
                    'contact': contact,
                    'birthday_date': next_bday,
                    'days_remaining': delta_days,
                    'turning_age': turning_age,
                    'is_today': (delta_days == 0),
                })

        upcoming.sort(key=lambda x: x['days_remaining'])
        return upcoming

    @classmethod
    def dispatch_daily_birthdays(cls, today=None, business_id=None, dry_run=False) -> dict:
        """
        Executes automated birthday SMS dispatch.
        Can be scoped to a single business or executed across all active automations.
        """
        if today is None:
            today = timezone.localdate()

        automations = BirthdayAutomation.objects.filter(is_enabled=True).select_related('business')
        if business_id:
            automations = automations.filter(business_id=business_id)

        stats = {
            'businesses_processed': 0,
            'birthdays_found': 0,
            'sent_count': 0,
            'skipped_count': 0,
            'failed_count': 0,
            'insufficient_credits_count': 0,
            'credits_spent': 0,
            'details': []
        }

        for automation in automations:
            business = automation.business
            stats['businesses_processed'] += 1

            # Find matching contacts
            contacts = Contact.objects.filter(
                business=business,
                is_subscribed=True,
                birth_date__month=today.month,
                birth_date__day=today.day
            )

            # Pre-filter suppressed contacts
            suppressed_numbers = set(
                SuppressionRecord.objects.filter(
                    phone_number__in=[c.phone_number for c in contacts]
                ).values_list('phone_number', flat=True)
            )

            sender_id = automation.sender_id or business.preferred_sender_id or 'TextBridge'
            provider = get_sms_provider()

            for contact in contacts:
                stats['birthdays_found'] += 1

                # 1. Check suppression list
                if contact.phone_number in suppressed_numbers:
                    stats['skipped_count'] += 1
                    stats['details'].append({
                        'business': business.name,
                        'contact': contact.name,
                        'phone': contact.phone_number,
                        'status': 'SKIPPED_SUPPRESSED'
                    })
                    continue

                # 2. Check idempotency (only 1 birthday message per contact per day)
                ref_id = f"BDAY_{business.id}_{contact.id}_{today.strftime('%Y%m%d')}"
                from billing.models import CreditLedgerEntry
                if CreditLedgerEntry.objects.filter(reference_id=ref_id).exists():
                    stats['skipped_count'] += 1
                    stats['details'].append({
                        'business': business.name,
                        'contact': contact.name,
                        'phone': contact.phone_number,
                        'status': 'ALREADY_SENT_TODAY'
                    })
                    continue

                # 3. Render message
                rendered_msg = cls.render_message(
                    template=automation.message_template,
                    contact_name=contact.name,
                    business_name=business.name
                )
                segment_info = calculate_sms_segments(rendered_msg)
                credits_needed = segment_info['segment_count']

                # Dry-run check
                if dry_run:
                    stats['sent_count'] += 1
                    stats['credits_spent'] += credits_needed
                    stats['details'].append({
                        'business': business.name,
                        'contact': contact.name,
                        'phone': contact.phone_number,
                        'message': rendered_msg,
                        'credits': credits_needed,
                        'status': 'DRY_RUN_ELIGIBLE'
                    })
                    continue

                # 4. Check credit balance & debit ledger atomically
                try:
                    CreditLedgerService.record_entry(
                        business_id=business.id,
                        entry_type='CAMPAIGN_USAGE_DEBIT',
                        amount=-credits_needed,
                        reference_id=ref_id,
                        description=f"Automated Birthday SMS to {contact.name} ({contact.phone_number})",
                        actor=None
                    )
                except InsufficientCreditsError:
                    stats['insufficient_credits_count'] += 1
                    stats['details'].append({
                        'business': business.name,
                        'contact': contact.name,
                        'phone': contact.phone_number,
                        'status': 'INSUFFICIENT_CREDITS'
                    })
                    logger.warning(f"Business {business.name} insufficient credits for Birthday SMS to {contact.phone_number}")
                    continue
                except DuplicateTransactionError:
                    stats['skipped_count'] += 1
                    continue

                # 5. Send via active telecom provider
                send_result = provider.send_single(
                    sender_id=sender_id,
                    recipient_phone=contact.phone_number,
                    message=rendered_msg
                )

                # 6. Record message log
                SMSMessage.objects.create(
                    business=business,
                    recipient_phone=contact.phone_number,
                    sender_id=sender_id,
                    message=rendered_msg,
                    status=SMSMessage.Status.DELIVERED if send_result.is_success else SMSMessage.Status.FAILED,
                    provider_message_id=send_result.provider_message_id or '',
                    credits_used=credits_needed
                )

                if send_result.is_success:
                    stats['sent_count'] += 1
                    stats['credits_spent'] += credits_needed
                    stats['details'].append({
                        'business': business.name,
                        'contact': contact.name,
                        'phone': contact.phone_number,
                        'status': 'SENT'
                    })
                else:
                    stats['failed_count'] += 1
                    stats['details'].append({
                        'business': business.name,
                        'contact': contact.name,
                        'phone': contact.phone_number,
                        'status': 'GATEWAY_FAILED',
                        'error': send_result.error_message
                    })

            # Update automation last_run_date
            if not dry_run:
                automation.last_run_date = today
                automation.save(update_fields=['last_run_date', 'updated_at'])

        return stats

    @classmethod
    def send_test_birthday_sms(cls, business: Business, test_phone: str, actor=None) -> dict:
        """
        Sends an immediate sample birthday greeting to test formatting and delivery.
        """
        automation, _ = BirthdayAutomation.objects.get_or_create(business=business)
        sender_id = automation.sender_id or business.preferred_sender_id or 'TextBridge'

        rendered = cls.render_message(
            template=automation.message_template,
            contact_name="Valued Customer",
            business_name=business.name
        )
        segment_info = calculate_sms_segments(rendered)
        credits_needed = segment_info['segment_count']

        if business.credit_balance < credits_needed:
            raise InsufficientCreditsError(
                f"Insufficient credits. Test requires {credits_needed} credit(s), current balance: {business.credit_balance}."
            )

        import uuid
        tx_ref = f"BDAY_TEST_{business.id}_{uuid.uuid4().hex[:8].upper()}"

        CreditLedgerService.record_entry(
            business_id=business.id,
            entry_type='CAMPAIGN_USAGE_DEBIT',
            amount=-credits_needed,
            reference_id=tx_ref,
            description=f"Test Birthday SMS greeting to {test_phone}",
            actor=actor
        )

        provider = get_sms_provider()
        res = provider.send_single(
            sender_id=sender_id,
            recipient_phone=test_phone,
            message=rendered
        )

        SMSMessage.objects.create(
            business=business,
            recipient_phone=test_phone,
            sender_id=sender_id,
            message=rendered,
            status=SMSMessage.Status.DELIVERED if res.is_success else SMSMessage.Status.FAILED,
            provider_message_id=res.provider_message_id or '',
            credits_used=credits_needed
        )

        return {
            'is_success': res.is_success,
            'message': rendered,
            'credits_used': credits_needed,
            'sender_id': sender_id,
            'error': res.error_message if not res.is_success else None
        }
