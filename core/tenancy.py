from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404


class TenantAccessError(PermissionDenied):
    pass


def get_user_business(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return None
    profile = getattr(user, "profile", None)
    if profile is None or profile.business_id is None:
        raise TenantAccessError("Your account is not linked to a business.")
    business = profile.business
    if not business.is_active or not profile.is_business_active:
        raise TenantAccessError(
            "Your business account has been deactivated. Contact admin."
        )
    return business


def scoped_qs(model, user):
    return model.objects.for_business(get_user_business(user))


def get_tenant_object(model, user, **lookup):
    business = get_user_business(user)
    return get_object_or_404(model.objects.for_business(business), **lookup)
