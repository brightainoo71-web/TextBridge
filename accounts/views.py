from messaging.models import WebhookEndpoint, WebhookDelivery
from messaging.webhook_service import WebhookService
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.db import transaction
from django.views.generic import View, TemplateView
from .forms import RegistrationForm, BusinessProfileForm
from .models import User, Business, BusinessMembership, AuditLog, APIKey
from .decorators import tenant_required
from messaging.models import SenderID


from billing.models import SMSPackage


class LandingPageView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('accounts:dashboard_redirect')
        packages = SMSPackage.objects.filter(is_active=True).order_by('price_ghs')[:4]
        return render(request, 'landing.html', {'packages': packages})


class RegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('accounts:dashboard_redirect')
        form = RegistrationForm()
        return render(request, 'accounts/register.html', {'form': form})

    @transaction.atomic
    def post(self, request):
        if request.user.is_authenticated:
            return redirect('accounts:dashboard_redirect')
        form = RegistrationForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            first_name = form.cleaned_data['first_name']
            last_name = form.cleaned_data['last_name']
            phone_number = form.cleaned_data['phone_number']

            biz_name = form.cleaned_data['business_name']
            biz_category = form.cleaned_data['business_category']
            preferred_sid = form.cleaned_data['preferred_sender_id']

            # 1. Create User
            user = User.objects.create_user(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone_number=phone_number,
                role=User.Role.BUSINESS_USER
            )

            # 2. Create Business
            business = Business.objects.create(
                name=biz_name,
                category=biz_category,
                contact_email=email,
                contact_phone=phone_number or '',
                preferred_sender_id=preferred_sid,
                status=Business.Status.ACTIVE
            )

            # 3. Create Membership (Owner)
            BusinessMembership.objects.create(
                user=user,
                business=business,
                role=BusinessMembership.Role.OWNER
            )

            # 4. Auto-register Sender ID request if provided
            if preferred_sid:
                SenderID.objects.create(
                    business=business,
                    sender_id=preferred_sid,
                    purpose=f"Primary sender ID for {biz_name}",
                    status=SenderID.Status.APPROVED
                )

            # 5. Log Registration
            AuditLog.objects.create(
                business=business,
                actor=user,
                action='BUSINESS_REGISTERED',
                description=f"New business '{biz_name}' registered by {email}"
            )

            # Send onboarding welcome email
            from .email_service import send_welcome_email
            send_welcome_email(user, business)

            # Log user in
            login(request, user)
            messages.success(request, f"Welcome to BrightSMS, {biz_name}! Your account has been initialized.")
            return redirect('accounts:onboarding')

        return render(request, 'accounts/register.html', {'form': form})


class LoginView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('accounts:dashboard_redirect')
        form = AuthenticationForm()
        return render(request, 'accounts/login.html', {'form': form})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('accounts:dashboard_redirect')
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name or user.email}!")
            return redirect('accounts:dashboard_redirect')
        return render(request, 'accounts/login.html', {'form': form})


class LogoutView(View):
    def post(self, request):
        logout(request)
        messages.info(request, "You have been securely logged out.")
        return redirect('accounts:login')

    def get(self, request):
        logout(request)
        return redirect('accounts:login')


class DashboardRedirectView(View):
    def get(self, request):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if request.user.is_superadmin:
            return redirect('analytics:admin_dashboard')
        return redirect('analytics:customer_dashboard')


class OnboardingView(View):
    def get(self, request):
        business = getattr(request, 'business', None)
        if not business:
            return redirect('accounts:login')

        contacts_count = business.contacts.count()
        balance = business.credit_balance
        has_purchased = business.purchases.filter(status='COMPLETED').exists()
        campaigns_count = business.campaigns.count()

        checklist = [
            {'step': 1, 'title': 'Create Business Profile', 'done': True, 'desc': 'Business profile and default sender ID configured.'},
            {'step': 2, 'title': 'Import Customer Contacts', 'done': contacts_count > 0, 'desc': f'{contacts_count} contact(s) imported.'},
            {'step': 3, 'title': 'Choose SMS Package', 'done': has_purchased or balance > 0, 'desc': 'Select an SMS package and acquire credits.'},
            {'step': 4, 'title': 'Send a Test or Live Campaign', 'done': campaigns_count > 0, 'desc': 'Compose your first message with personalized fields.'},
            {'step': 5, 'title': 'Review Delivery Reports', 'done': campaigns_count > 0, 'desc': 'Track delivered, queued, or failed SMS reports in real-time.'},
        ]

        return render(request, 'accounts/onboarding.html', {
            'business': business,
            'checklist': checklist,
            'contacts_count': contacts_count,
            'balance': balance
        })


class BusinessProfileView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        form = BusinessProfileForm(instance=business)
        return render(request, 'accounts/profile.html', {'form': form, 'business': business})

    @tenant_required
    def post(self, request):
        business = request.business
        form = BusinessProfileForm(request.POST, instance=business)
        if form.is_valid():
            form.save()
            messages.success(request, "Business profile updated successfully.")
            return redirect('accounts:profile')
        return render(request, 'accounts/profile.html', {'form': form, 'business': business})


class SuspendedNoticeView(TemplateView):
    template_name = 'accounts/suspended_notice.html'


class DeveloperApiKeysView(View):
    @tenant_required
    def get(self, request):
        business = request.business
        api_keys = business.api_keys.all()
        new_key = request.session.pop('newly_generated_api_key', None)
        return render(request, 'accounts/developer_keys.html', {
            'business': business,
            'api_keys': api_keys,
            'new_key': new_key
        })

    @tenant_required
    def post(self, request):
        business = request.business
        key_name = request.POST.get('name', '').strip() or 'Live Secret Key'
        instance, raw_key = APIKey.generate(business=business, name=key_name)
        request.session['newly_generated_api_key'] = {
            'name': instance.name,
            'raw_key': raw_key,
            'prefix': instance.prefix
        }
        messages.success(request, f"New API key '{instance.name}' generated! Copy it now as it won't be shown again.")
        return redirect('accounts:developer_keys')


class RevokeApiKeyView(View):
    @tenant_required
    def post(self, request, pk):
        business = request.business
        key = get_object_or_404(APIKey, pk=pk, business=business)
        key.is_active = False
        key.save(update_fields=['is_active'])
        messages.warning(request, f"API key '{key.name}' ({key.prefix}...) has been revoked.")
        return redirect('accounts:developer_keys')


class SaveWebhookEndpointView(View):
    @tenant_required
    def post(self, request):
        business = request.business
        url = request.POST.get('url', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        selected_events = request.POST.getlist('events')

        if not url:
            messages.error(request, "Webhook URL cannot be empty.")
            return redirect('accounts:developer_keys')

        if not url.startswith('https://') and not url.startswith('http://127.0.0.1') and not url.startswith('http://localhost'):
            messages.error(request, "Webhook URL must begin with https:// (or http://localhost for testing).")
            return redirect('accounts:developer_keys')

        endpoint = WebhookEndpoint.objects.filter(business=business).first()
        if endpoint:
            endpoint.url = url
            endpoint.is_active = is_active
            endpoint.events = selected_events if selected_events else ['sms.delivered', 'sms.failed']
            endpoint.save()
            messages.success(request, f"Webhook settings updated for {endpoint.url}.")
        else:
            endpoint = WebhookEndpoint.create_endpoint(
                business=business,
                url=url,
                events=selected_events if selected_events else ['sms.delivered', 'sms.failed']
            )
            endpoint.is_active = is_active
            endpoint.save()
            messages.success(request, "Webhook endpoint created! Your secret signing key is ready.")

        return redirect('accounts:developer_keys')


class TestWebhookPingView(View):
    @tenant_required
    def post(self, request):
        business = request.business
        endpoint = WebhookEndpoint.objects.filter(business=business).first()
        if not endpoint:
            messages.error(request, "Please configure a webhook URL first before testing.")
            return redirect('accounts:developer_keys')

        delivery = WebhookService.send_test_ping(endpoint)
        if delivery.is_success:
            messages.success(
                request,
                f"Test webhook delivered successfully! Remote server responded with HTTP {delivery.response_status_code} "
                f"in {delivery.duration_ms}ms."
            )
        else:
            err = delivery.error_message or f"HTTP {delivery.response_status_code}"
            messages.warning(
                request,
                f"Test webhook dispatched, but remote server returned: {err} ({delivery.duration_ms}ms)."
            )
        return redirect('accounts:developer_keys')


class RegenerateWebhookSecretView(View):
    @tenant_required
    def post(self, request):
        business = request.business
        endpoint = WebhookEndpoint.objects.filter(business=business).first()
        if endpoint:
            endpoint.secret_key = f"whsec_{secrets.token_hex(24)}"
            endpoint.save(update_fields=['secret_key'])
            messages.success(request, "New webhook signing secret generated! Update your verification server.")
        return redirect('accounts:developer_keys')
