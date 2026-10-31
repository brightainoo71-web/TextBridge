import csv
import uuid
import json
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import HttpResponse, JsonResponse
from django.views.generic import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.contrib import messages
from accounts.decorators import tenant_required
from .models import SMSPackage, Purchase, PaymentTransaction, CreditLedgerEntry
from .ledger_service import CreditLedgerService, DuplicateTransactionError
from .payment_adapters import get_payment_adapter


class PackagesView(View):
    @tenant_required
    def get(self, request):
        packages = SMSPackage.objects.filter(is_active=True).order_by('price_ghs')
        return render(request, 'billing/packages.html', {
            'packages': packages,
            'balance': request.business.credit_balance
        })


class CheckoutInitiateView(View):
    @tenant_required
    def post(self, request, package_id):
        business = request.business
        package = get_object_or_404(SMSPackage, id=package_id, is_active=True)

        # Generate unique reference
        ref = f"PUR_{business.id}_{uuid.uuid4().hex[:10].upper()}"

        purchase = Purchase.objects.create(
            business=business,
            package=package,
            credits_granted=package.credits,
            amount_paid=package.effective_price,
            currency='GHS',
            status=Purchase.Status.PENDING,
            payment_reference=ref
        )

        callback_url = request.build_absolute_uri(reverse('billing:payment_callback'))

        adapter = get_payment_adapter()
        init_result = adapter.initialize_transaction(purchase, callback_url)

        if 'error' in init_result:
            messages.error(request, f"Unable to start checkout: {init_result['error']}")
            purchase.status = Purchase.Status.FAILED
            purchase.save(update_fields=['status'])
            return redirect('billing:packages')

        # Record initialized transaction
        PaymentTransaction.objects.create(
            purchase=purchase,
            provider=PaymentTransaction.Provider.SANDBOX if init_result.get('is_sandbox') else PaymentTransaction.Provider.PAYSTACK,
            transaction_reference=ref,
            raw_response=init_result,
            status=PaymentTransaction.Status.INITIALIZED
        )

        # Redirect user to provider checkout URL
        auth_url = init_result.get('authorization_url')
        return redirect(auth_url)


class SandboxCheckoutView(View):
    """
    Simulated Paystack/Mobile Money Checkout Screen for testing in development.
    """
    def get(self, request, reference):
        purchase = get_object_or_404(Purchase, payment_reference=reference)
        return render(request, 'billing/sandbox_checkout.html', {
            'purchase': purchase,
            'reference': reference
        })

    def post(self, request, reference):
        purchase = get_object_or_404(Purchase, payment_reference=reference)
        action = request.POST.get('action')

        if action == 'success':
            # Complete purchase and credit ledger safely
            try:
                CreditLedgerService.record_entry(
                    business_id=purchase.business.id,
                    entry_type='PURCHASE_CREDIT',
                    amount=purchase.credits_granted,
                    reference_id=f"PAY_VERIFY_{purchase.payment_reference}",
                    description=f"Purchased package '{purchase.package.name}' ({purchase.credits_granted:,} SMS)",
                    purchase=purchase,
                    actor=request.user if request.user.is_authenticated else None
                )

                purchase.status = Purchase.Status.COMPLETED
                purchase.completed_at = timezone.now()
                purchase.save(update_fields=['status', 'completed_at'])

                tx = purchase.transactions.first()
                if tx:
                    tx.status = PaymentTransaction.Status.SUCCESS
                    tx.save(update_fields=['status'])

                # Send purchase receipt email
                from accounts.email_service import send_purchase_receipt_email
                send_purchase_receipt_email(purchase)

                messages.success(
                    request,
                    f"Payment successful! {purchase.credits_granted:,} SMS credits have been added to your balance."
                )
                return redirect('billing:purchase_history')

            except DuplicateTransactionError:
                messages.info(request, "This payment was already confirmed and credited.")
                return redirect('billing:purchase_history')
        else:
            purchase.status = Purchase.Status.FAILED
            purchase.save(update_fields=['status'])
            messages.error(request, "Simulated payment was cancelled or declined.")
            return redirect('billing:packages')


class PaymentCallbackView(View):
    """
    Return endpoint from live Paystack payment gateway.
    """
    def get(self, request):
        reference = request.GET.get('reference') or request.GET.get('trxref')
        if not reference:
            messages.error(request, "No transaction reference returned.")
            return redirect('billing:packages')

        purchase = get_object_or_404(Purchase, payment_reference=reference)

        adapter = get_payment_adapter()
        verify_result = adapter.verify_transaction(reference)

        if verify_result.is_success:
            try:
                CreditLedgerService.record_entry(
                    business_id=purchase.business.id,
                    entry_type='PURCHASE_CREDIT',
                    amount=purchase.credits_granted,
                    reference_id=f"PAY_CALLBACK_{reference}",
                    description=f"Purchased package '{purchase.package.name}' ({purchase.credits_granted:,} SMS)",
                    purchase=purchase,
                    actor=request.user if request.user.is_authenticated else None
                )

                purchase.status = Purchase.Status.COMPLETED
                purchase.completed_at = timezone.now()
                purchase.save(update_fields=['status', 'completed_at'])

                PaymentTransaction.objects.update_or_create(
                    purchase=purchase,
                    transaction_reference=reference,
                    defaults={
                        'status': PaymentTransaction.Status.SUCCESS,
                        'provider_fee': verify_result.provider_fee,
                        'raw_response': verify_result.raw_data
                    }
                )

                from accounts.email_service import send_purchase_receipt_email
                send_purchase_receipt_email(purchase)

                messages.success(request, f"Payment verified! {purchase.credits_granted:,} SMS credits added.")
            except DuplicateTransactionError:
                messages.info(request, "Payment was already verified and credited.")
        else:
            purchase.status = Purchase.Status.FAILED
            purchase.save(update_fields=['status'])
            messages.error(request, f"Payment verification failed: {verify_result.error_message}")

        return redirect('billing:purchase_history')


@method_decorator(csrf_exempt, name='dispatch')
class PaystackWebhookView(View):
    """
    Server-to-server Paystack Webhook listener with HMAC-SHA512 verification.
    """
    def post(self, request):
        signature = request.headers.get('x-paystack-signature', '')
        adapter = get_payment_adapter()

        if not adapter.verify_webhook_signature(request.body, signature):
            return HttpResponse("Invalid signature", status=400)

        try:
            event_data = json.loads(request.body.decode('utf-8'))
        except json.JSONDecodeError:
            return HttpResponse("Invalid payload", status=400)

        event = event_data.get('event')
        data = event_data.get('data', {})

        if event == 'charge.success':
            reference = data.get('reference')
            purchase = Purchase.objects.filter(payment_reference=reference).first()
            if purchase and purchase.status != Purchase.Status.COMPLETED:
                try:
                    CreditLedgerService.record_entry(
                        business_id=purchase.business.id,
                        entry_type='PURCHASE_CREDIT',
                        amount=purchase.credits_granted,
                        reference_id=f"PAY_WEBHOOK_{reference}",
                        description=f"Webhook confirmed purchase of {purchase.credits_granted:,} SMS credits",
                        purchase=purchase
                    )
                    purchase.status = Purchase.Status.COMPLETED
                    purchase.completed_at = timezone.now()
                    purchase.save(update_fields=['status', 'completed_at'])

                    PaymentTransaction.objects.update_or_create(
                        purchase=purchase,
                        transaction_reference=reference,
                        defaults={
                            'status': PaymentTransaction.Status.SUCCESS,
                            'provider_fee': Decimal(str(data.get('fees', 0) or 0)) / Decimal('100.0'),
                            'raw_response': data
                        }
                    )

                    from accounts.email_service import send_purchase_receipt_email
                    send_purchase_receipt_email(purchase)
                except DuplicateTransactionError:
                    pass

        return HttpResponse("Webhook received", status=200)


class PurchaseHistoryView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        purchases = Purchase.objects.filter(business=business).order_by('-created_at')
        return render(request, 'billing/purchase_history.html', {
            'purchases': purchases,
            'balance': business.credit_balance
        })


class CreditLedgerView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        entries = CreditLedgerEntry.objects.filter(business=business).order_by('-created_at')
        return render(request, 'billing/credit_ledger.html', {
            'entries': entries,
            'balance': business.credit_balance
        })


class LedgerExportView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        entries = CreditLedgerEntry.objects.filter(business=business).order_by('-created_at')

        now_str = timezone.now().strftime('%Y%m%d_%H%M')
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="TextBridge_Credit_Ledger_{now_str}.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Reference ID',
            'Entry Type',
            'Amount',
            'Balance After',
            'Description',
            'Purchase Reference',
            'Actor',
            'Timestamp'
        ])

        for e in entries.iterator():
            purchase_ref = e.purchase.payment_reference if e.purchase else ''
            actor_name = e.actor.get_full_name() or e.actor.email if e.actor else 'System'
            writer.writerow([
                e.reference_id,
                e.entry_type,
                e.amount,
                e.balance_after,
                e.description,
                purchase_ref,
                actor_name,
                e.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])

        return response

