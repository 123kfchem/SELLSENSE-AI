from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.models import User

from .forms import (
    BusinessProfileUpdateForm,
    BusinessRegistrationForm,
    ItemForm,
    ItemReportForm,
    RoleSelectionForm,
    SaleForm,
)
from .models import Item, ItemReport, UserProfile
from .services import ai_item_suggestions, ml_sales_analysis_table, sales_summary

REGISTRATION_MANAGER_USERNAME = "erickmonyancha"


class BusinessLoginView(LoginView):
    template_name = "login.html"


def business_logout(request):
    logout(request)
    return render(request, "logout.html")


@login_required
def business_register(request):
    if request.user.username != REGISTRATION_MANAGER_USERNAME:
        messages.error(request, "Only erickmonyancha can register businesses.")
        return redirect("role-select")

    businesses = (
        UserProfile.objects.select_related("user")
        .exclude(role__isnull=True)
        .exclude(role__exact="")
        .order_by("-user__date_joined")
    )

    if request.method == "POST":
        action = request.POST.get("action", "create")
        if action == "create":
            form = BusinessRegistrationForm(request.POST)
            if form.is_valid():
                role = form.cleaned_data["role"]
                user = form.save(commit=False)
                user.email = form.cleaned_data.get("email", "")
                user.first_name = form.cleaned_data.get("first_name", "")
                user.last_name = form.cleaned_data.get("last_name", "")
                user.is_active = True
                user.save()
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.role = role
                profile.business_name = form.cleaned_data.get("business_name", "")
                profile.phone_number = form.cleaned_data.get("phone_number", "")
                profile.location = form.cleaned_data.get("location", "")
                profile.is_business_active = True
                profile.save(
                    update_fields=[
                        "role",
                        "business_name",
                        "phone_number",
                        "location",
                        "is_business_active",
                    ]
                )
                messages.success(request, f"Business account '{user.username}' created as {role}.")
                return redirect("business-register")
        elif action == "toggle":
            profile = get_object_or_404(UserProfile, pk=request.POST.get("profile_id"))
            profile.is_business_active = not profile.is_business_active
            profile.save(update_fields=["is_business_active"])
            state = "activated" if profile.is_business_active else "deactivated"
            messages.info(request, f"{profile.user.username} has been {state}.")
            return redirect("business-register")
        elif action == "update":
            profile = get_object_or_404(UserProfile, pk=request.POST.get("profile_id"))
            update_form = BusinessProfileUpdateForm(request.POST, instance=profile)
            if update_form.is_valid():
                update_form.save()
                messages.success(request, f"{profile.user.username} profile updated.")
                return redirect("business-register")
        form = BusinessRegistrationForm()
    else:
        form = BusinessRegistrationForm()
    return render(request, "business_register.html", {"form": form, "businesses": businesses})


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@login_required
def role_select(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = RoleSelectionForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            return redirect("employer-dashboard" if profile.role == "employer" else "employee-dashboard")
    else:
        form = RoleSelectionForm(instance=profile)
    return render(request, "role_select.html", {"form": form})


def _require_role(user, role):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile.role == role and profile.is_business_active


@login_required
def employer_dashboard(request):
    if not _require_role(request.user, "employer"):
        return redirect("role-select")

    items = Item.objects.exclude(status=Item.STATUS_DELETED).order_by("-created_at")
    item_form = ItemForm()
    report_form = ItemReportForm()
    ai_data = ai_item_suggestions()
    ml_analysis_rows = ml_sales_analysis_table("weekly")
    daily_sales, daily_revenue, daily_units = sales_summary("daily")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add_item":
            item_form = ItemForm(request.POST)
            if item_form.is_valid():
                item = item_form.save(commit=False)
                item.created_by = request.user
                item.save()
                messages.success(request, "Item added successfully.")
                return redirect("employer-dashboard")

        elif action in {"delete_item", "cancel_item"}:
            item = get_object_or_404(Item, pk=request.POST.get("item_id"))
            item.status = Item.STATUS_DELETED if action == "delete_item" else Item.STATUS_CANCELLED
            item.save(update_fields=["status"])
            messages.info(request, f"Item {item.name} marked as {item.status}.")
            return redirect("employer-dashboard")

        elif action == "report_item":
            item = get_object_or_404(Item, pk=request.POST.get("item_id"))
            report_form = ItemReportForm(request.POST)
            if report_form.is_valid():
                report = report_form.save(commit=False)
                report.item = item
                report.reported_by = request.user
                report.save()
                messages.success(request, f"Report submitted for {item.name}.")
                return redirect("employer-dashboard")

    context = {
        "items": items,
        "item_form": item_form,
        "report_form": report_form,
        "ai_data": ai_data,
        "ml_analysis_rows": ml_analysis_rows,
        "daily_sales": daily_sales,
        "daily_revenue": daily_revenue,
        "daily_units": daily_units,
    }
    return render(request, "employer_dashboard.html", context)


@login_required
def reports_view(request, period):
    if not _require_role(request.user, "employer"):
        return redirect("role-select")
    if period not in {"daily", "weekly", "monthly"}:
        period = "daily"

    sales, revenue, units = sales_summary(period)
    ml_analysis_rows = ml_sales_analysis_table(period)
    return render(
        request,
        "reports.html",
        {
            "period": period,
            "sales": sales,
            "revenue": revenue,
            "units": units,
            "ml_analysis_rows": ml_analysis_rows,
        },
    )


@login_required
def employee_dashboard(request):
    if not _require_role(request.user, "employee"):
        return redirect("role-select")

    active_items = Item.objects.filter(status=Item.STATUS_ACTIVE).order_by("name")
    sale_form = SaleForm()
    sale_form.fields["item"].queryset = active_items

    if request.method == "POST":
        sale_form = SaleForm(request.POST)
        sale_form.fields["item"].queryset = active_items
        if sale_form.is_valid():
            sale = sale_form.save(commit=False)
            sale.sold_by = request.user
            sale.total_amount = Decimal(sale.quantity) * sale.item.unit_price
            sale.save()
            messages.success(request, "Sale processed successfully.")
            return redirect("employee-dashboard")

    daily_sales, daily_revenue, daily_units = sales_summary("daily")
    return render(
        request,
        "employee_dashboard.html",
        {
            "sale_form": sale_form,
            "daily_sales": daily_sales,
            "daily_revenue": daily_revenue,
            "daily_units": daily_units,
        },
    )
