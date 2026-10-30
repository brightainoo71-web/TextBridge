from django.db import transaction
from django.core.exceptions import ValidationError
from accounts.models import Business, AuditLog
from .models import CreditLedgerEntry


class InsufficientCreditsError(Exception):
    pass


class DuplicateTransactionError(Exception):
    pass


class CreditLedgerService:
    """
    Guarantees concurrency-safe, idempotent, auditable balance tracking.
    Never allows negative balances or duplicate webhook/campaign credits.
    """

    @classmethod
    @transaction.atomic
    def record_entry(
        cls,
        business_id: int,
        entry_type: str,
        amount: int,
        reference_id: str,
        description: str,
        purchase=None,
        campaign_id=None,
        actor=None
    ) -> CreditLedgerEntry:
        # Check idempotency first
        if CreditLedgerEntry.objects.filter(reference_id=reference_id).exists():
            raise DuplicateTransactionError(f"Transaction with reference {reference_id} has already been processed.")

        # Row-level lock on Business record
        business = Business.objects.select_for_update().get(id=business_id)

        new_balance = business.credit_balance + amount
        if new_balance < 0:
            raise InsufficientCreditsError(
                f"Insufficient SMS credits. Required: {abs(amount)}, Available: {business.credit_balance}."
            )

        # Create immutable ledger entry
        ledger_entry = CreditLedgerEntry.objects.create(
            business=business,
            entry_type=entry_type,
            amount=amount,
            balance_after=new_balance,
            purchase=purchase,
            campaign_id=campaign_id,
            description=description,
            actor=actor,
            reference_id=reference_id
        )

        # Update business cached balance
        business.credit_balance = new_balance
        business.save(update_fields=['credit_balance', 'updated_at'])

        # Audit Log
        AuditLog.objects.create(
            business=business,
            actor=actor,
            action=f"CREDIT_{entry_type}",
            description=f"{description} (Delta: {amount:+d}, New Balance: {new_balance})",
            metadata={'ledger_entry_id': ledger_entry.id, 'reference_id': reference_id}
        )

        return ledger_entry

    @classmethod
    def get_verified_balance(cls, business_id: int) -> int:
        """
        Derives balance by summing all ledger entries or reads from latest entry.
        """
        latest = CreditLedgerEntry.objects.filter(business_id=business_id).order_by('-created_at').first()
        return latest.balance_after if latest else 0
