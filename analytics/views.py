import csv
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.views.generic import View
from django.contrib import messages
from django.db.models import Sum, Count, Q
from accounts.models import Business, User, AuditLog
from accounts.decorators import tenant_required, superadmin_required
from contacts.models import Contact
from billing.models import Purchase, SMSPackage, CreditLedgerEntry
from billing.ledger_service import CreditLedgerService
from messaging.models import SMSCampaign, CampaignRecipient
from messaging.providers import get_sms_provider


class CustomerDashboardView(View):
    @tenant_required
    def get(self, request):
        business = request.business

        # Analytics
        contacts_count = Contact.objects.filter(business=business).count()
        campaigns_count = SMSCampaign.objects.filter(business=business).count()
        recent_campaigns = SMSCampaign.objects.filter(business=business).order_by('-created_at')[:5]
        recent_purchases = Purchase.objects.filter(business=business).order_by('-created_at')[:5]

        # Delivery statistics across all campaigns for this business
        stats = CampaignRecipient.objects.filter(campaign__business=business).aggregate(
            total=Count('id'),
            delivered=Count('id', filter=Q(status='DELIVERED')),
            accepted=Count('id', filter=Q(status='ACCEPTED')),
            failed=Count('id', filter=Q(status='FAILED')),
            queued=Count('id', filter=Q(status='QUEUED'))
        )

        return render(request, 'analytics/customer_dashboard.html', {
            'business': business,
            'balance': business.credit_balance,
            'contacts_count': contacts_count,
            'campaigns_count': campaigns_count,
            'recent_campaigns': recent_campaigns,
            'recent_purchases': recent_purchases,
            'stats': stats,
        })


class AdminDashboardView(View):
    @superadmin_required
    def get(self, request):
        total_businesses = Business.objects.count()
        active_businesses = Business.objects.filter(status='ACTIVE').count()
        suspended_businesses = Business.objects.filter(status='SUSPENDED').count()

        # Financials from completed purchases
        completed_purchases = Purchase.objects.filter(status='COMPLETED')
        gross_sales = completed_purchases.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
        total_credits_sold = completed_purchases.aggregate(Sum('credits_granted'))['credits_granted__sum'] or 0

        # Provider costs estimation
        # We can calculate based on total delivered messages * default cost per segment
        total_dispatched_recipients = CampaignRecipient.objects.filter(status__in=['DELIVERED', 'ACCEPTED']).count()
        estimated_provider_cost = Decimal(str(total_dispatched_recipients)) * Decimal('0.0350')
        estimated_margin = gross_sales - estimated_provider_cost

        # Overall message metrics
        message_stats = CampaignRecipient.objects.aggregate(
            total=Count('id'),
            delivered=Count('id', filter=Q(status='DELIVERED')),
            accepted=Count('id', filter=Q(status='ACCEPTED')),
            failed=Count('id', filter=Q(status='FAILED'))
        )

        # SMS Provider Health & Balance check
        provider = get_sms_provider()
        provider_info = provider.get_balance()

        # Recent Platform Audit Logs
        recent_logs = AuditLog.objects.select_related('business', 'actor').order_by('-created_at')[:10]
        recent_businesses = Business.objects.order_by('-created_at')[:5]

        return render(request, 'analytics/admin_dashboard.html', {
            'total_businesses': total_businesses,
            'active_businesses': active_businesses,
            'suspended_businesses': suspended_businesses,
            'gross_sales': gross_sales,
            'total_credits_sold': total_credits_sold,
            'estimated_provider_cost': estimated_provider_cost,
            'estimated_margin': estimated_margin,
            'message_stats': message_stats,
            'provider_info': provider_info,
            'recent_logs': recent_logs,
            'recent_businesses': recent_businesses,
        })


class AdminBusinessListView(View):
    @superadmin_required
    def get(self, request):
        query = request.GET.get('q', '').strip()
        businesses = Business.objects.all().order_by('-created_at')
        if query:
            businesses = businesses.filter(Q(name__icontains=query) | Q(contact_email__icontains=query))

        return render(request, 'analytics/admin_business_list.html', {
            'businesses': businesses,
            'query': query
        })


class AdminBusinessActionView(View):
    @superadmin_required
    def post(self, request, pk):
        business = get_object_or_404(Business, pk=pk)
        action = request.POST.get('action')

        if action == 'suspend':
            business.status = Business.Status.SUSPENDED
            business.save(update_fields=['status'])
            AuditLog.objects.create(
                business=business,
                actor=request.user,
                action='BUSINESS_SUSPENDED',
                description=f"Business '{business.name}' suspended by Admin {request.user.email}"
            )
            messages.warning(request, f"Business '{business.name}' has been suspended.")

        elif action == 'reactivate':
            business.status = Business.Status.ACTIVE
            business.save(update_fields=['status'])
            AuditLog.objects.create(
                business=business,
                actor=request.user,
                action='BUSINESS_REACTIVATED',
                description=f"Business '{business.name}' reactivated by Admin {request.user.email}"
            )
            messages.success(request, f"Business '{business.name}' is now active.")

        elif action == 'adjust_credits':
            try:
                credit_amount = int(request.POST.get('credit_amount', 0))
                reason = request.POST.get('reason', 'Administrative manual adjustment')
                if credit_amount != 0:
                    import uuid
                    ref_id = f"ADMIN_ADJ_{business.id}_{uuid.uuid4().hex[:8].upper()}"
                    CreditLedgerService.record_entry(
                        business_id=business.id,
                        entry_type='ADMIN_ADJUSTMENT',
                        amount=credit_amount,
                        reference_id=ref_id,
                        description=f"Admin credit adjustment: {reason}",
                        actor=request.user
                    )
                    messages.success(request, f"Adjusted {credit_amount:+d} credits for '{business.name}'.")
            except Exception as e:
                messages.error(request, f"Failed to adjust credits: {str(e)}")

        return redirect('analytics:admin_business_list')


class AdminAuditLogListView(View):
    @superadmin_required
    def get(self, request):
        logs = AuditLog.objects.select_related('business', 'actor').order_by('-created_at')[:100]
        return render(request, 'analytics/admin_audit_logs.html', {'logs': logs})


class ExportReportView(View):
    @tenant_required
    def get(self, request, report_type):
        business = request.business
        response = HttpResponse(content_type='text/csv')

        if report_type == 'campaigns':
            response['Content-Disposition'] = f'attachment; filename="{business.slug}_campaigns.csv"'
            writer = csv.writer(response)
            writer.writerow(['ID', 'Title', 'Sender ID', 'Status', 'Total Contacts', 'Delivered', 'Credits Used', 'Created At'])
            campaigns = SMSCampaign.objects.filter(business=business).order_by('-created_at')
            for c in campaigns:
                writer.writerow([c.id, c.title, c.sender_id, c.status, c.total_recipients, c.actual_credits_used, c.created_at.strftime('%Y-%m-%d %H:%M')])

        elif report_type == 'contacts':
            response['Content-Disposition'] = f'attachment; filename="{business.slug}_contacts.csv"'
            writer = csv.writer(response)
            writer.writerow(['Name', 'Phone Number', 'Email', 'Is Subscribed', 'Created At'])
            contacts = Contact.objects.filter(business=business).order_by('name')
            for c in contacts:
                writer.writerow([c.name, c.phone_number, c.email or '', c.is_subscribed, c.created_at.strftime('%Y-%m-%d')])

        elif report_type == 'purchases':
            response['Content-Disposition'] = f'attachment; filename="{business.slug}_purchases.csv"'
            writer = csv.writer(response)
            writer.writerow(['Reference', 'Package', 'Credits', 'Amount Paid', 'Currency', 'Status', 'Date'])
            purchases = Purchase.objects.filter(business=business).order_by('-created_at')
            for p in purchases:
                pkg_name = p.package.name if p.package else 'Custom'
                writer.writerow([p.payment_reference, pkg_name, p.credits_granted, p.amount_paid, p.currency, p.status, p.created_at.strftime('%Y-%m-%d %H:%M')])

        else:
            return HttpResponse("Invalid report type", status=400)

        return response
