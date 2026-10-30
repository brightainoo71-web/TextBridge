from django.conf import settings


def platform_context(request):
    """
    Exposes platform brand configuration and current tenant context to all templates.
    """
    business = getattr(request, 'business', None)
    membership = getattr(request, 'membership', None)
    is_superadmin = getattr(request, 'is_superadmin', False)

    return {
        'PLATFORM_NAME': getattr(settings, 'PLATFORM_NAME', 'BrightSMS'),
        'PLATFORM_TAGLINE': getattr(settings, 'PLATFORM_TAGLINE', 'Multi-Business SMS SaaS'),
        'PRIMARY_CURRENCY': getattr(settings, 'PRIMARY_CURRENCY', 'GHS'),
        'CURRENCY_SYMBOL': getattr(settings, 'CURRENCY_SYMBOL', 'GH₵'),
        'ACTIVE_SMS_PROVIDER': getattr(settings, 'ACTIVE_SMS_PROVIDER', 'MOCK'),
        'current_business': business,
        'current_membership': membership,
        'is_superadmin': is_superadmin,
    }
