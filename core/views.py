from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.db.models import Count, F, Sum
from django.db.models.functions import Coalesce
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.contrib.auth.models import User

from .forms import (
    BusinessProfileUpdateForm,
    BusinessRegistrationForm,
    ItemForm,
    ItemReportForm,
    RoleSelectionForm,
    SaleForm,
)
from .models import Item, ItemReport, Sale, UserProfile
from .services import ai_item_suggestions, ml_sales_analysis_table, sales_summary
from django.http import HttpResponse

def home(request):
    return HttpResponse("SELLSENSE AI is live 🚀")

class BusinessLoginView(LoginView):
    template_name = "login.html"

    def get_success_url(self):
        self.request.session.pop("active_role", None)
        if self.request.user.is_superuser:
            return reverse("superuser-dashboard")
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        if profile.is_business_active:
            return reverse("role-select")
        return reverse("role-select")


def home(request):
    return render(request, "home.html")


def business_logout(request):
    logout(request)
    return render(request, "logout.html")


@login_required
def superuser_dashboard(request):
    if not request.user.is_superuser:
        messages.error(request, "Only superusers can access this page.")
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
                employer_password = form.cleaned_data.get("employer_password")
                if employer_password:
                    profile.set_employer_password(employer_password)
                profile.save(
                    update_fields=[
                        "role",
                        "business_name",
                        "phone_number",
                        "location",
                        "is_business_active",
                        "employer_password_hash",
                    ]
                )
                messages.success(request, f"Business account '{user.username}' created as {role}.")
                return redirect("superuser-dashboard")
        elif action == "toggle":
            profile = get_object_or_404(UserProfile, pk=request.POST.get("profile_id"))
            profile.is_business_active = not profile.is_business_active
            profile.save(update_fields=["is_business_active"])
            state = "activated" if profile.is_business_active else "deactivated"
            messages.info(request, f"{profile.user.username} has been {state}.")
            return redirect("superuser-dashboard")
        elif action == "update":
            profile = get_object_or_404(UserProfile, pk=request.POST.get("profile_id"))
            update_form = BusinessProfileUpdateForm(request.POST, instance=profile)
            if update_form.is_valid():
                update_form.save()
                messages.success(request, f"{profile.user.username} profile updated.")
                return redirect("superuser-dashboard")
        form = BusinessRegistrationForm()
    else:
        form = BusinessRegistrationForm()
    return render(request, "superuser_dashboard.html", {"form": form, "businesses": businesses})


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@login_required
def role_select(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_business_active:
        messages.error(request, "Your business account is currently inactive.")
        return redirect("logout")
    if request.method == "POST":
        form = RoleSelectionForm(request.POST)
        if form.is_valid():
            selected_role = form.cleaned_data["role"]
            employer_password = form.cleaned_data.get("employer_password", "")
            if selected_role == UserProfile.ROLE_EMPLOYER:
                if not profile.employer_password_hash:
                    messages.error(request, "Employer password has not been configured by admin.")
                    return redirect("role-select")
                if not profile.check_employer_password(employer_password):
                    messages.error(request, "Invalid employer password.")
                    return redirect("role-select")
            request.session["active_role"] = selected_role
            return redirect("employer-dashboard" if selected_role == "employer" else "employee-dashboard")
    else:
        form = RoleSelectionForm(initial={"role": profile.role or UserProfile.ROLE_EMPLOYEE})
    return render(request, "role_select.html", {"form": form})


def _require_role(request, role):
    user = request.user
    if not user.is_authenticated:
        return False
    profile, _ = UserProfile.objects.get_or_create(user=user)
    session_role = request.session.get("active_role")
    return session_role == role and profile.is_business_active


def _record_sale_with_stock(item, quantity, user, payment_method, mpesa_amount_sent):
    with transaction.atomic():
        rows_updated = Item.objects.filter(pk=item.pk, current_quantity__gte=quantity).update(
            current_quantity=F("current_quantity") - quantity,
        )
        if rows_updated == 0:
            return None
        Item.objects.filter(pk=item.pk).update(stock_qty=F("current_quantity"))
        item.refresh_from_db(fields=["unit_price"])
        sale = Sale.objects.create(
            item=item,
            quantity=quantity,
            sold_by=user,
            payment_method=payment_method,
            mpesa_amount_sent=mpesa_amount_sent,
            total_amount=Decimal(quantity) * item.unit_price,
        )
        return sale


def _stock_insights_queryset():
    return (
        Item.objects.exclude(status=Item.STATUS_DELETED)
        .annotate(total_sold=Coalesce(Sum("sales__quantity"), 0))
        .order_by("name")
    )


@login_required
def employer_dashboard(request):
    if not _require_role(request, "employer"):
        return redirect("role-select")

    items = Item.objects.exclude(status=Item.STATUS_DELETED).order_by("-created_at")
    active_items = Item.objects.filter(status=Item.STATUS_ACTIVE, current_quantity__gt=0).order_by("name")
    item_form = ItemForm()
    sale_form = SaleForm()
    sale_form.fields["item"].queryset = active_items
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
                item.current_quantity = item.initial_quantity
                item.stock_qty = item.initial_quantity
                item.save()
                messages.success(request, "Item added successfully.")
                return redirect("employer-dashboard")

        elif action == "record_sale":
            sale_form = SaleForm(request.POST)
            sale_form.fields["item"].queryset = active_items
            if sale_form.is_valid():
                sale = sale_form.save(commit=False)
                recorded = _record_sale_with_stock(
                    item=sale.item,
                    quantity=sale.quantity,
                    user=request.user,
                    payment_method=sale.payment_method,
                    mpesa_amount_sent=sale.mpesa_amount_sent,
                )
                if not recorded:
                    messages.error(request, f"Insufficient stock for {sale.item.name}.")
                    return redirect("employer-dashboard")
                messages.success(request, "Sale recorded successfully.")
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

    stock_insights = _stock_insights_queryset()
    context = {
        "items": items,
        "item_form": item_form,
        "sale_form": sale_form,
        "report_form": report_form,
        "ai_data": ai_data,
        "ml_analysis_rows": ml_analysis_rows,
        "daily_sales": daily_sales,
        "daily_revenue": daily_revenue,
        "daily_units": daily_units,
        "stock_insights": stock_insights,
    }
    return render(request, "employer_dashboard.html", context)


@login_required
def reports_view(request, period):
    if not _require_role(request, "employer"):
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
    if not _require_role(request, "employee"):
        return redirect("role-select")

    active_items = Item.objects.filter(status=Item.STATUS_ACTIVE, current_quantity__gt=0).order_by("name")
    sale_form = SaleForm()
    sale_form.fields["item"].queryset = active_items

    if request.method == "POST":
        sale_form = SaleForm(request.POST)
        sale_form.fields["item"].queryset = active_items
        if sale_form.is_valid():
            sale = sale_form.save(commit=False)
            recorded = _record_sale_with_stock(
                item=sale.item,
                quantity=sale.quantity,
                user=request.user,
                payment_method=sale.payment_method,
                mpesa_amount_sent=sale.mpesa_amount_sent,
            )
            if not recorded:
                messages.error(request, f"Insufficient stock for {sale.item.name}.")
                return redirect("employee-dashboard")
            messages.success(request, "Sale processed successfully.")
            return redirect("employee-dashboard")

    daily_sales, daily_revenue, daily_units = sales_summary("daily")
    my_daily_sales = daily_sales.filter(sold_by=request.user)
    my_daily_units = my_daily_sales.aggregate(total=Sum("quantity"))["total"] or 0
    my_daily_revenue = my_daily_sales.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    item_prices = {str(item.pk): str(item.unit_price) for item in active_items}
    return render(
        request,
        "employee_dashboard.html",
        {
            "sale_form": sale_form,
            "daily_sales": daily_sales,
            "daily_revenue": daily_revenue,
            "daily_units": daily_units,
            "my_daily_units": my_daily_units,
            "my_daily_revenue": my_daily_revenue,
            "item_prices": item_prices,
        },
    )


@login_required
def sales_analytics_api(request):
    if not _require_role(request, "employer"):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    insights = list(_stock_insights_queryset().values("name", "total_sold"))
    return JsonResponse({"items": insights})


@login_required
def stock_insights_api(request):
    if not _require_role(request, "employer"):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    insights = list(_stock_insights_queryset().values("name", "current_quantity", "total_sold"))
    return JsonResponse({"items": insights})


@login_required
def superuser_business_stats_api(request):
    if not request.user.is_superuser:
        return JsonResponse({"detail": "Forbidden"}, status=403)
    base_qs = UserProfile.objects.exclude(role__isnull=True).exclude(role__exact="")
    role_counts = list(base_qs.values("role").annotate(total=Count("id")).order_by("role"))
    status_counts = list(base_qs.values("is_business_active").annotate(total=Count("id")))
    payload = {
        "role_counts": [
            {
                "label": row["role"].title(),
                "total": row["total"],
            }
            for row in role_counts
        ],
        "status_counts": [
            {
                "label": "Active" if row["is_business_active"] else "Inactive",
                "total": row["total"],
            }
            for row in status_counts
        ],
        "total_businesses": base_qs.count(),
    }
    return JsonResponse(payload)
