from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import UserProfile


class TenantAccessError(PermissionDenied):
    pass


def get_user_business(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return None
    try:
        profile = UserProfile.objects.select_related("business").get(user=user)
    except UserProfile.DoesNotExist:
        raise TenantAccessError("Your account is not linked to a business.")
    if profile.business_id is None:
        raise TenantAccessError("Your account is not linked to a business.")
    business = profile.business
    if business.sync_payment_status():
        business.save(update_fields=["payment_status"])
    if business.payment_status == business.PAYMENT_OVERDUE:
        raise TenantAccessError(
            "Your subscription payment is overdue. Contact admin to restore access."
        )
    if not business.is_active or not profile.is_business_active:
        raise TenantAccessError(
            "Your business account has been deactivated. Contact admin."
        )
    return business


def assert_business_access(user, business):
    """Raise TenantAccessError when business is not the user's tenant."""
    allowed = get_user_business(user)
    if business is None or allowed.pk != business.pk:
        raise TenantAccessError("Cross-tenant access denied.")


def scoped_qs(model, user):
    return model.objects.for_business(get_user_business(user))


def get_tenant_object(model, user, **lookup):
    business = get_user_business(user)
    return get_object_or_404(model.objects.for_business(business), **lookup)
