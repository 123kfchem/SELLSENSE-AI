from django.utils.functional import SimpleLazyObject

from .tenancy import TenantAccessError, get_user_business


def _load_business(request):
    if not request.user.is_authenticated:
        return None
    try:
        return get_user_business(request.user)
    except TenantAccessError:
        return None


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.business = SimpleLazyObject(lambda: _load_business(request))
        return self.get_response(request)
