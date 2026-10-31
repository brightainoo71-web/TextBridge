# Contacts views module
import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.contrib import messages
from django.views.generic import View, ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.db.models import Q
from django.utils import timezone
from accounts.decorators import tenant_required
from contacts.utils import normalize_phone_number
from billing.ledger_service import InsufficientCreditsError
from .models import Contact, ContactGroup, ContactGroupMembership, SuppressionRecord, BirthdayAutomation
from .forms import ContactForm, ContactGroupForm, ContactImportForm, SuppressionForm, BirthdayAutomationForm
from .importer import ContactImporter
from .birthday_service import BirthdayAutomationService


class ContactListView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        query = request.GET.get('q', '').strip()
        group_id = request.GET.get('group', '').strip()

        contacts = Contact.objects.filter(business=business).prefetch_related('group_memberships__group')

        if query:
            contacts = contacts.filter(
                Q(name__icontains=query) | Q(phone_number__icontains=query) | Q(email__icontains=query)
            )

        selected_group = None
        if group_id:
            contacts = contacts.filter(group_memberships__group_id=group_id)
            selected_group = ContactGroup.objects.filter(business=business, id=group_id).first()

        from django.core.paginator import Paginator
        paginator = Paginator(contacts, 25)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        groups = ContactGroup.objects.filter(business=business)

        return render(request, 'contacts/contact_list.html', {
            'page_obj': page_obj,
            'groups': groups,
            'selected_group': selected_group,
            'query': query,
            'total_count': contacts.count(),
        })


class ContactCreateView(View):
    @tenant_required
    def get(self, request):
        form = ContactForm(business=request.business)
        return render(request, 'contacts/contact_form.html', {'form': form, 'title': 'Add New Contact'})

    @tenant_required
    def post(self, request):
        business = request.business
        form = ContactForm(request.POST, business=business)
        if form.is_valid():
            contact = form.save(commit=False)
            contact.business = business
            # Check unique constraint within business
            if Contact.objects.filter(business=business, phone_number=contact.phone_number).exists():
                form.add_error('phone_number', "A contact with this phone number already exists in your workspace.")
                return render(request, 'contacts/contact_form.html', {'form': form, 'title': 'Add New Contact'})

            contact.save()
            group = form.cleaned_data.get('group')
            if group:
                ContactGroupMembership.objects.create(contact=contact, group=group)

            messages.success(request, f"Contact '{contact.name}' ({contact.phone_number}) created successfully.")
            return redirect('contacts:contact_list')

        return render(request, 'contacts/contact_form.html', {'form': form, 'title': 'Add New Contact'})


class ContactUpdateView(View):
    @tenant_required
    def get(self, request, pk):
        business = request.business
        contact = get_object_or_404(Contact, pk=pk, business=business)
        initial_group = contact.group_memberships.first()
        initial_group_id = initial_group.group.id if initial_group else None
        form = ContactForm(instance=contact, business=business, initial={'group': initial_group_id})
        return render(request, 'contacts/contact_form.html', {'form': form, 'title': f'Edit {contact.name}'})

    @tenant_required
    def post(self, request, pk):
        business = request.business
        contact = get_object_or_404(Contact, pk=pk, business=business)
        form = ContactForm(request.POST, instance=contact, business=business)
        if form.is_valid():
            contact = form.save()
            group = form.cleaned_data.get('group')
            contact.group_memberships.all().delete()
            if group:
                ContactGroupMembership.objects.create(contact=contact, group=group)

            messages.success(request, f"Contact '{contact.name}' updated successfully.")
            return redirect('contacts:contact_list')

        return render(request, 'contacts/contact_form.html', {'form': form, 'title': f'Edit {contact.name}'})


class ContactDeleteView(View):
    @tenant_required
    def post(self, request, pk):
        business = request.business
        contact = get_object_or_404(Contact, pk=pk, business=business)
        name = contact.name
        contact.delete()
        messages.success(request, f"Contact '{name}' deleted.")
        return redirect('contacts:contact_list')


class ContactGroupListView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        groups = ContactGroup.objects.filter(business=business).order_by('name')
        form = ContactGroupForm()
        return render(request, 'contacts/group_list.html', {'groups': groups, 'form': form})

    @tenant_required
    def post(self, request):
        business = request.business
        form = ContactGroupForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data['name']
            if ContactGroup.objects.filter(business=business, name__iexact=name).exists():
                messages.error(request, f"A group named '{name}' already exists.")
            else:
                group = form.save(commit=False)
                group.business = business
                group.save()
                messages.success(request, f"Group '{group.name}' created.")
            return redirect('contacts:group_list')
        groups = ContactGroup.objects.filter(business=business)
        return render(request, 'contacts/group_list.html', {'groups': groups, 'form': form})


class ContactGroupDeleteView(View):
    @tenant_required
    def post(self, request, pk):
        business = request.business
        group = get_object_or_404(ContactGroup, pk=pk, business=business)
        name = group.name
        group.delete()
        messages.success(request, f"Group '{name}' deleted. (Contacts within the group remain in your database).")
        return redirect('contacts:group_list')


class ContactImportView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        form = ContactImportForm(business=business)
        return render(request, 'contacts/import.html', {'form': form})

    @tenant_required
    def post(self, request):
        business = request.business
        form = ContactImportForm(request.POST, request.FILES, business=business)
        if form.is_valid():
            uploaded_file = form.cleaned_data['file']
            group = form.cleaned_data.get('group')
            duplicate_policy = form.cleaned_data.get('duplicate_policy')

            importer = ContactImporter(
                business=business,
                group_id=group.id if group else None,
                duplicate_policy=duplicate_policy
            )

            try:
                # Direct processing
                results = importer.process_import(uploaded_file)
                messages.success(
                    request,
                    f"Import completed! Added: {results['created_count']}, Updated: {results['updated_count']}, "
                    f"Skipped: {results['skipped_count']}, Invalid: {results['invalid_count']}."
                )
                return render(request, 'contacts/import_result.html', {
                    'results': results,
                    'group': group,
                    'policy': duplicate_policy,
                })
            except Exception as e:
                messages.error(request, f"Failed to process file: {str(e)}")

        return render(request, 'contacts/import.html', {'form': form})


class DownloadSampleTemplateView(View):
    def get(self, request):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="BrightSMS_Contact_Template.csv"'

        writer = csv.writer(response)
        writer.writerow(['Full Name', 'Phone Number', 'Email Address'])
        writer.writerow(['Kofi Mensah', '0241234567', 'kofi@example.com'])
        writer.writerow(['Ama Serwaa', '0209876543', 'ama@example.com'])
        writer.writerow(['Kwame Asante', '0540001122', 'kwame@example.com'])
        return response


class SuppressionListView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        suppressions = SuppressionRecord.objects.filter(
            Q(business=business) | Q(business__isnull=True)
        ).order_by('-created_at')
        form = SuppressionForm()
        return render(request, 'contacts/suppression_list.html', {
            'suppressions': suppressions,
            'form': form
        })

    @tenant_required
    def post(self, request):
        business = request.business
        form = SuppressionForm(request.POST)
        if form.is_valid():
            sup = form.save(commit=False)
            sup.business = business
            sup.save()
            messages.success(request, f"Phone number {sup.phone_number} added to opt-out/suppression list.")
            return redirect('contacts:suppression_list')

        suppressions = SuppressionRecord.objects.filter(
            Q(business=business) | Q(business__isnull=True)
        ).order_by('-created_at')
        return render(request, 'contacts/suppression_list.html', {
            'suppressions': suppressions,
            'form': form
        })


class SuppressionDeleteView(View):
    @tenant_required
    def post(self, request, pk):
        business = request.business
        sup = get_object_or_404(SuppressionRecord, pk=pk, business=business)
        phone = sup.phone_number
        sup.delete()
        messages.success(request, f"Phone number {phone} removed from suppression list.")
        return redirect('contacts:suppression_list')


class ContactExportView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        query = request.GET.get('q', '').strip()
        group_id = request.GET.get('group', '').strip()

        contacts = Contact.objects.filter(business=business).prefetch_related('group_memberships__group')

        if query:
            contacts = contacts.filter(
                Q(name__icontains=query) | Q(phone_number__icontains=query) | Q(email__icontains=query)
            )

        if group_id:
            contacts = contacts.filter(group_memberships__group_id=group_id)

        now_str = timezone.now().strftime('%Y%m%d_%H%M')
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="TextBridge_Contacts_{now_str}.csv"'

        writer = csv.writer(response)
        writer.writerow(['Full Name', 'Phone Number', 'Email', 'Birth Date', 'Subscription Status', 'Groups', 'Date Added'])

        for c in contacts.iterator(chunk_size=1000):
            groups = "; ".join([gm.group.name for gm in c.group_memberships.all()])
            bdate = c.birth_date.strftime('%Y-%m-%d') if c.birth_date else ''
            sub_status = "Subscribed" if c.is_subscribed else "Unsubscribed"
            writer.writerow([
                c.name,
                c.phone_number,
                c.email or '',
                bdate,
                sub_status,
                groups,
                c.created_at.strftime('%Y-%m-%d %H:%M')
            ])

        return response


class BirthdayAutomationView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        automation, _ = BirthdayAutomation.objects.get_or_create(business=business)
        form = BirthdayAutomationForm(instance=automation, business=business)
        upcoming = BirthdayAutomationService.get_upcoming_birthdays(business, days=14)
        
        # Recent birthday dispatches
        from messaging.models import SMSMessage
        recent_dispatches = SMSMessage.objects.filter(
            business=business,
            message__icontains="Birthday"
        ).order_by('-created_at')[:10]

        return render(request, 'contacts/birthday_automation.html', {
            'automation': automation,
            'form': form,
            'upcoming_birthdays': upcoming,
            'recent_dispatches': recent_dispatches,
            'credit_balance': business.credit_balance,
        })

    @tenant_required
    def post(self, request):
        business = request.business
        automation, _ = BirthdayAutomation.objects.get_or_create(business=business)
        form = BirthdayAutomationForm(request.POST, instance=automation, business=business)
        if form.is_valid():
            automation = form.save(commit=False)
            automation.business = business
            automation.save()
            status_text = "activated" if automation.is_enabled else "paused"
            messages.success(request, f"Birthday SMS automation settings saved ({status_text}).")
            return redirect('contacts:birthday_automation')

        upcoming = BirthdayAutomationService.get_upcoming_birthdays(business, days=14)
        return render(request, 'contacts/birthday_automation.html', {
            'automation': automation,
            'form': form,
            'upcoming_birthdays': upcoming,
            'credit_balance': business.credit_balance,
        })


class BirthdayTestDispatchView(View):
    @tenant_required
    def post(self, request):
        business = request.business
        test_phone = request.POST.get('test_phone', '').strip()
        is_valid, normalized, err = normalize_phone_number(test_phone)

        if not is_valid:
            messages.error(request, f"Invalid Ghanaian phone number: {err}")
            return redirect('contacts:birthday_automation')

        try:
            res = BirthdayAutomationService.send_test_birthday_sms(
                business=business,
                test_phone=normalized,
                actor=request.user
            )
            if res['is_success']:
                messages.success(
                    request,
                    f"Test Birthday SMS successfully sent to {normalized} via Sender ID '{res['sender_id']}'. "
                    f"Credits used: {res['credits_used']}."
                )
            else:
                messages.error(request, f"Gateway error sending test SMS: {res['error']}")
        except InsufficientCreditsError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Failed to send test birthday greeting: {str(e)}")

        return redirect('contacts:birthday_automation')

