from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import PermissionDenied


def _extract_request(args):
    """
    Extracts HttpRequest object whether the decorator wraps a function view `func(request)`
    or a class-based view method `func(self, request)`.
    """
    if len(args) > 0 and hasattr(args[0], 'user'):
        return args[0]
    elif len(args) > 1 and hasattr(args[1], 'user'):
        return args[1]
    return None


def tenant_required(view_func):
    """
    Decorator for views that require an active business tenant context.
    Prevents unauthenticated users and users without an active business from accessing.
    """
    @wraps(view_func)
    def _wrapped_view(*args, **kwargs):
        request = _extract_request(args)
        if not request or not request.user.is_authenticated:
            return redirect('accounts:login')
        
        # If user is superadmin, they might access customer views if an active business is chosen,
        # or they can be redirected to admin dashboard if they don't have a business context
        if request.user.is_superadmin:
            if not getattr(request, 'business', None):
                return redirect('analytics:admin_dashboard')
            return view_func(*args, **kwargs)

        business = getattr(request, 'business', None)
        if not business:
            messages.error(request, "Your account is not linked to an active business or your business is pending setup.")
            return redirect('accounts:onboarding')

        if business.status == 'SUSPENDED':
            messages.error(request, "Your business account is suspended. Please contact platform support.")
            return redirect('accounts:suspended_notice')

        return view_func(*args, **kwargs)
    return _wrapped_view


def superadmin_required(view_func):
    """
    Decorator for platform super administrator views.
    """
    @wraps(view_func)
    def _wrapped_view(*args, **kwargs):
        request = _extract_request(args)
        if not request or not request.user.is_authenticated:
            return redirect('accounts:login')
        if not request.user.is_superadmin:
            messages.error(request, "Access denied. Platform Administrator privileges required.")
            return redirect('accounts:dashboard_redirect')
        return view_func(*args, **kwargs)
    return _wrapped_view
