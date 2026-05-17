from django.contrib import admin

from .models import Business, Item, ItemReport, Sale, UserProfile


class TenantAdminMixin:
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if hasattr(request.user, "profile") and request.user.profile.business_id:
            return qs.filter(business=request.user.profile.business)
        return qs.none()


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "phone_number", "location", "is_active", "created_at")
    search_fields = ("name",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "business", "role", "is_business_active")
    list_filter = ("role", "is_business_active")


@admin.register(Item)
class ItemAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("name", "business", "unit_price", "current_quantity", "status")


@admin.register(Sale)
class SaleAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("item", "business", "quantity", "total_amount", "sold_at", "sold_by")


@admin.register(ItemReport)
class ItemReportAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("item", "business", "reported_by", "created_at")
