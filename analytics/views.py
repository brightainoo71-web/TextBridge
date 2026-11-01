import csv
import uuid
from decimal import Decimal
from django.utils import timezone
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
from messaging.models import SMSCampaign, CampaignRecipient, SenderID
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

        elif action == 'add_sender_id':
            raw_sid = request.POST.get('sender_id', '').strip()
            purpose = request.POST.get('purpose', '').strip()
            status = request.POST.get('status', SenderID.Status.APPROVED)
            clean_sid = ''.join(ch for ch in raw_sid if ch.isalnum()).upper()[:11]
            if clean_sid:
                sid, created = SenderID.objects.get_or_create(
                    business=business,
                    sender_id=clean_sid,
                    defaults={
                        'purpose': purpose or f"Provisioned by Administrator for {business.name}",
                        'status': status,
                        'approved_at': timezone.now() if status == SenderID.Status.APPROVED else None
                    }
                )
                if not created:
                    sid.status = status
                    if status == SenderID.Status.APPROVED:
                        sid.approved_at = timezone.now()
                    sid.save()
                if status == SenderID.Status.APPROVED:
                    business.preferred_sender_id = clean_sid
                    business.save(update_fields=['preferred_sender_id'])
                AuditLog.objects.create(
                    business=business,
                    actor=request.user,
                    action='SENDER_ID_PROVISIONED',
                    description=f"Admin provisioned Sender ID '{clean_sid}' ({status}) for {business.name}"
                )
                messages.success(request, f"Sender ID '{clean_sid}' successfully assigned to '{business.name}'.")
            else:
                messages.error(request, "Invalid Sender ID. Must be 1-11 alphanumeric characters.")

        return redirect('analytics:admin_business_list')


class AdminSenderIDListView(View):
    """
    Superadmin Command Center for provisioned, pending, and platform-wide Sender IDs.
    Allows the platform administrator to request, approve, reject, or assign Sender IDs
    for any registered tenant account or system-wide default.
    """
    @superadmin_required
    def get(self, request):
        status_filter = request.GET.get('status', '').strip().upper()
        search_query = request.GET.get('q', '').strip()

        sender_ids = SenderID.objects.select_related('business').order_by('-created_at')
        if status_filter:
            sender_ids = sender_ids.filter(status=status_filter)
        if search_query:
            sender_ids = sender_ids.filter(
                Q(sender_id__icontains=search_query) |
                Q(business__name__icontains=search_query) |
                Q(purpose__icontains=search_query)
            )

        businesses = Business.objects.filter(status=Business.Status.ACTIVE).order_by('name')
        pending_count = SenderID.objects.filter(status=SenderID.Status.PENDING).count()
        approved_count = SenderID.objects.filter(status=SenderID.Status.APPROVED).count()
        system_defaults_count = SenderID.objects.filter(is_system_default=True).count()

        return render(request, 'analytics/admin_sender_id_list.html', {
            'sender_ids': sender_ids,
            'businesses': businesses,
            'status_filter': status_filter,
            'search_query': search_query,
            'pending_count': pending_count,
            'approved_count': approved_count,
            'system_defaults_count': system_defaults_count,
        })

    @superadmin_required
    def post(self, request):
        action = request.POST.get('action')

        if action == 'create':
            business_id = request.POST.get('business_id')
            raw_sid = request.POST.get('sender_id', '').strip()
            purpose = request.POST.get('purpose', '').strip()
            initial_status = request.POST.get('status', SenderID.Status.APPROVED)
            is_system_default = request.POST.get('is_system_default') == '1'

            clean_sid = ''.join(ch for ch in raw_sid if ch.isalnum()).upper()[:11]
            if not clean_sid:
                messages.error(request, "Sender ID must contain 1-11 alphanumeric characters.")
                return redirect('analytics:admin_sender_ids')

            business = None
            if not is_system_default:
                if not business_id:
                    messages.error(request, "Please select a registered business, or toggle 'Platform System Default'.")
                    return redirect('analytics:admin_sender_ids')
                business = get_object_or_404(Business, pk=business_id)

            # Check duplication
            if business and SenderID.objects.filter(business=business, sender_id=clean_sid).exists():
                messages.warning(request, f"Sender ID '{clean_sid}' is already assigned to {business.name}.")
                return redirect('analytics:admin_sender_ids')
            elif is_system_default and SenderID.objects.filter(is_system_default=True, sender_id=clean_sid).exists():
                messages.warning(request, f"Platform System Default Sender ID '{clean_sid}' already exists.")
                return redirect('analytics:admin_sender_ids')

            new_sid = SenderID.objects.create(
                business=business,
                sender_id=clean_sid,
                purpose=purpose or f"Provisioned by Superadmin for {business.name if business else 'Platform'}",
                status=initial_status,
                is_system_default=is_system_default,
                approved_at=timezone.now() if initial_status == SenderID.Status.APPROVED else None
            )

            if business and (not business.preferred_sender_id or initial_status == SenderID.Status.APPROVED):
                business.preferred_sender_id = clean_sid
                business.save(update_fields=['preferred_sender_id'])

            target_label = business.name if business else "Platform-Wide Default"
            AuditLog.objects.create(
                business=business,
                actor=request.user,
                action='SENDER_ID_PROVISIONED',
                description=f"Admin {request.user.email} provisioned Sender ID '{clean_sid}' ({initial_status}) for {target_label}"
            )
            messages.success(request, f"Sender ID '{clean_sid}' provisioned for {target_label}.")
            return redirect('analytics:admin_sender_ids')

        sid_id = request.POST.get('sender_id_id')
        sid = get_object_or_404(SenderID, pk=sid_id)

        if action == 'approve':
            sid.status = SenderID.Status.APPROVED
            sid.approved_at = timezone.now()
            sid.save(update_fields=['status', 'approved_at'])
            if sid.business and not sid.business.preferred_sender_id:
                sid.business.preferred_sender_id = sid.sender_id
                sid.business.save(update_fields=['preferred_sender_id'])
            AuditLog.objects.create(
                business=sid.business,
                actor=request.user,
                action='SENDER_ID_APPROVED',
                description=f"Admin approved and activated Sender ID '{sid.sender_id}'"
            )
            messages.success(request, f"Sender ID '{sid.sender_id}' approved and activated for {sid.business.name if sid.business else 'Platform'}.")

        elif action == 'reject':
            reason = request.POST.get('reason', 'Administrative decision').strip()
            sid.status = SenderID.Status.REJECTED
            sid.rejection_reason = reason
            sid.save(update_fields=['status', 'rejection_reason'])
            AuditLog.objects.create(
                business=sid.business,
                actor=request.user,
                action='SENDER_ID_REJECTED',
                description=f"Admin rejected Sender ID '{sid.sender_id}': {reason}"
            )
            messages.warning(request, f"Sender ID '{sid.sender_id}' was rejected.")

        elif action == 'delete':
            sid_name = sid.sender_id
            target_label = sid.business.name if sid.business else "Platform Default"
            sid.delete()
            AuditLog.objects.create(
                business=sid.business,
                actor=request.user,
                action='SENDER_ID_DELETED',
                description=f"Admin deleted Sender ID '{sid_name}' from {target_label}"
            )
            messages.info(request, f"Sender ID '{sid_name}' was removed.")

        return redirect('analytics:admin_sender_ids')


class AdminAuditLogListView(View):
    @superadmin_required
    def get(self, request):
        if AuditLog.objects.count() == 0:
            AuditLog.objects.create(
                business=None,
                actor=request.user,
                action='SYSTEM_ONLINE',
                description=f"TextBridge Multi-Tenant Telecom SaaS initialized and online (Superadmin: {request.user.email})"
            )
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
