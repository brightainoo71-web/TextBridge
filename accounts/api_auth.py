import functools
from django.http import JsonResponse
from django.utils import timezone
from .models import APIKey, Business


def require_api_key(view_func):
    """
    Decorator for public REST API endpoints.
    Authenticates requests using secret API keys:
      Authorization: Bearer tb_live_...
      or X-API-Key: tb_live_...
    """
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        api_key_header = request.headers.get('X-API-Key', '')
        raw_key = ''

        if auth_header.startswith('Bearer '):
            raw_key = auth_header[7:].strip()
        elif api_key_header:
            raw_key = api_key_header.strip()

        if not raw_key:
            return JsonResponse({
                "error": "Unauthorized",
                "message": "Missing API key. Pass 'Authorization: Bearer tb_live_...' or 'X-API-Key: tb_live_...' header."
            }, status=401)

        prefix = raw_key[:16]
        matching_keys = APIKey.objects.filter(prefix=prefix, is_active=True).select_related('business')
        
        valid_key = None
        for key in matching_keys:
            if key.verify(raw_key):
                valid_key = key
                break

        if not valid_key:
            return JsonResponse({
                "error": "Unauthorized",
                "message": "Invalid or revoked API key."
            }, status=401)

        business = valid_key.business
        if business.status != Business.Status.ACTIVE:
            return JsonResponse({
                "error": "Forbidden",
                "message": f"Business account '{business.name}' is currently {business.status.lower()}."
            }, status=403)

        # Attach to request
        request.business = business
        request.api_key = valid_key

        # Update last used timestamp
        valid_key.last_used_at = timezone.now()
        valid_key.save(update_fields=['last_used_at'])

        return view_func(request, *args, **kwargs)

    return wrapper
