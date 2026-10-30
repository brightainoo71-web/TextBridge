from .models import BusinessMembership


class TenantMiddleware:
    """
    Ensures every authenticated request has an associated tenant (business) context
    and role context attached to `request`.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.business = None
        request.membership = None
        request.is_superadmin = False

        if request.user.is_authenticated:
            request.is_superadmin = request.user.is_superadmin

            if request.is_superadmin:
                # If an admin is impersonating or viewing a specific business via session:
                selected_biz_id = request.session.get('admin_active_business_id')
                if selected_biz_id:
                    from .models import Business
                    request.business = Business.objects.filter(id=selected_biz_id).first()
            else:
                membership = (
                    BusinessMembership.objects
                    .filter(user=request.user, is_active=True)
                    .exclude(business__status='DEACTIVATED')
                    .select_related('business')
                    .first()
                )
                if membership:
                    request.membership = membership
                    request.business = membership.business

        response = self.get_response(request)
        return response
