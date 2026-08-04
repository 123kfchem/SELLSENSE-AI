from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Count, F, Sum
from django.db.models.functions import Coalesce
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


from .forms import (
    BusinessAuthenticationForm,
    BusinessProfileUpdateForm,
    BusinessRegistrationForm,
    ContactForm,
    ExpenseForm,
    ItemForm,
    PaymentNoticeForm,
    PostForm,
    RoleSelectionForm,
    SaleForm,
    SuperuserPasswordResetForm,
)
from .models import Business, Expense, Item, ItemReport, Post, Sale, UserProfile
from .pdf_reports import (
    PDFGenerationError,
    build_daily_sales_pdf,
    build_period_summary_pdf,
    build_weekly_ml_report_pdf,
)
from .services import (
    ai_item_suggestions,
    ensure_business_year_start,
    ensure_weekly_ml_reports,
    expenses_summary,
    ml_sales_analysis_table,
    period_profit_report,
    profit_summary,
    sales_summary,
    weekly_ml_report_history,
    _quantize_money,
)
from .tenancy import (
    TenantAccessError,
    assert_business_access,
    get_tenant_object,
    get_user_business,
    scoped_qs,
)


def _send_contact_email(contact_form):
    recipient = settings.CONTACT_EMAIL
    if not recipient:
        return False

    data = contact_form.cleaned_data
    company_name = data.get("company_name") or "Not provided"
    subject = f"SellSense AI Contact: {data['subject']}"
    body = "\n".join(
        [
            "New contact form submission from SellSense AI.",
            "",
            f"Full name: {data['full_name']}",
            f"Phone number: {data['phone_number']}",
            f"Email: {data['email']}",
            f"Company name: {company_name}",
            f"Subject: {data['subject']}",
            "",
            "Message:",
            data["message"],
        ]
    )
    email = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
        reply_to=[data["email"]],
    )
    email.send(fail_silently=False)
    return True


class BusinessLoginView(LoginView):
    template_name = "login.html"
    authentication_form = BusinessAuthenticationForm

    def get_success_url(self):
        self.request.session.pop("active_role", None)
        if self.request.user.is_superuser:
            return reverse("superuser-dashboard")
        return reverse("role-select")


def home(request):
    contact_form = ContactForm()
    if request.method == "POST" and request.POST.get("form_type") == "contact":
        contact_form = ContactForm(request.POST)
        if contact_form.is_valid():
            try:
                sent = _send_contact_email(contact_form)
            except Exception:
                sent = False
            if sent:
                messages.success(
                    request,
                    "Thank you for reaching out! Our team will respond to your inquiry shortly.",
                )
                return redirect(f"{reverse('home')}?contact_sent=1#contact")
            messages.error(
                request,
                "Your message could not be sent right now. Please try again later.",
            )
    return render(
        request,
        "home.html",
        {
            "contact_form": contact_form,
            "contact_sent": request.GET.get("contact_sent") == "1",
            "posts": Post.objects.filter(is_published=True).select_related("author")[:20],
        },
    )


def service_worker(request):
    sw_path = Path(settings.BASE_DIR) / "static" / "sw.js"
    try:
        return HttpResponse(sw_path.read_text(encoding="utf-8"), content_type="application/javascript")
    except FileNotFoundError:
        return HttpResponse("/* Service worker not found */", content_type="application/javascript", status=404)


def business_logout(request):
    logout(request)
    return render(request, "logout.html")


def _require_tenant_business(request):
    try:
        return get_user_business(request.user)
    except TenantAccessError as exc:
        messages.error(request, str(exc))
        return None


@login_required
def superuser_dashboard(request):
    if not request.user.is_superuser:
        messages.error(request, "Only superusers can access this page.")
        return redirect("role-select")

    businesses = (
        UserProfile.objects.select_related("user", "business")
        .exclude(role__isnull=True)
        .exclude(role__exact="")
        .order_by("-user__date_joined")
    )

    form = BusinessRegistrationForm()
    post_form = PostForm()

    if request.method == "POST":
        action = request.POST.get("action", "create")
        if action == "create":
            form = BusinessRegistrationForm(request.POST)
            if form.is_valid():
                role = form.cleaned_data["role"]
                business_name = form.cleaned_data["business_name"].strip()
                business = Business.objects.create(
                    name=business_name,
                    phone_number=form.cleaned_data.get("phone_number", ""),
                    location=form.cleaned_data.get("location", ""),
                )

                user = form.save(commit=False)
                user.email = form.cleaned_data.get("email", "")
                user.first_name = form.cleaned_data.get("first_name", "")
                user.last_name = form.cleaned_data.get("last_name", "")
                user.is_active = True
                user.save()
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.role = role
                profile.business = business
                profile.is_business_active = True
                employer_password = form.cleaned_data.get("employer_password")
                if employer_password:
                    profile.set_employer_password(employer_password)
                profile.save(
                    update_fields=[
                        "role",
                        "business",
                        "is_business_active",
                        "employer_password_hash",
                    ]
                )
                messages.success(
                    request,
                    f"Business account '{user.username}' created for {business.name} as {role}.",
                )
                return redirect("superuser-dashboard")
        elif action == "toggle":
            profile = get_object_or_404(UserProfile, pk=request.POST.get("profile_id"))
            profile.is_business_active = not profile.is_business_active
            profile.save(update_fields=["is_business_active"])
            if profile.business_id:
                profile.business.is_active = profile.is_business_active
                profile.business.save(update_fields=["is_active"])
            state = "activated" if profile.is_business_active else "deactivated"
            messages.info(request, f"{profile.user.username} has been {state}.")
            return redirect("superuser-dashboard")
        elif action == "update":
            profile = get_object_or_404(
                UserProfile.objects.select_related("business"),
                pk=request.POST.get("profile_id"),
            )
            update_form = BusinessProfileUpdateForm(request.POST, profile=profile)
            if update_form.is_valid():
                update_form.save()
                messages.success(request, f"{profile.user.username} profile updated.")
                return redirect("superuser-dashboard")
        elif action == "reset_password":
            profile = get_object_or_404(
                UserProfile.objects.select_related("user"),
                pk=request.POST.get("profile_id"),
            )
            reset_form = SuperuserPasswordResetForm(request.POST, profile=profile)
            if reset_form.is_valid():
                reset_form.save()
                updated_parts = []
                if reset_form.cleaned_data.get("login_password"):
                    updated_parts.append("login password")
                if reset_form.cleaned_data.get("employer_password"):
                    updated_parts.append("employer password")
                messages.success(
                    request,
                    f"Updated {' and '.join(updated_parts)} for {profile.user.username}.",
                )
            else:
                for error in reset_form.non_field_errors():
                    messages.error(request, error)
                for field_errors in reset_form.errors.values():
                    for error in field_errors:
                        messages.error(request, error)
            return redirect("superuser-dashboard")
        elif action == "send_payment_notice":
            business = get_object_or_404(
                Business,
                pk=request.POST.get("business_id"),
            )
            notice_form = PaymentNoticeForm(request.POST, business=business)
            if notice_form.is_valid():
                notice_form.save()
                messages.success(
                    request,
                    f"Payment notice sent to {business.name}. Only users in this business will see it.",
                )
            else:
                for field_errors in notice_form.errors.values():
                    for error in field_errors:
                        messages.error(request, error)
            return redirect("superuser-dashboard")
        elif action == "clear_payment_notice":
            business = get_object_or_404(
                Business,
                pk=request.POST.get("business_id"),
            )
            business.payment_status = Business.PAYMENT_OK
            business.amount_due = None
            business.due_date = None
            business.payment_notice = ""
            business.notice_sent_at = None
            business.save(
                update_fields=[
                    "payment_status",
                    "amount_due",
                    "due_date",
                    "payment_notice",
                    "notice_sent_at",
                ]
            )
            messages.success(
                request,
                f"Payment notice cleared for {business.name}.",
            )
            return redirect("superuser-dashboard")
        elif action == "create_post":
            post_form = PostForm(request.POST, request.FILES)
            if post_form.is_valid():
                post = post_form.save(commit=False)
                post.author = request.user
                post.save()
                messages.success(request, "Post published on the homepage.")
                return redirect("superuser-dashboard")
            for field_errors in post_form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
        elif action == "delete_post":
            post = get_object_or_404(Post, pk=request.POST.get("post_id"))
            post.delete()
            messages.success(request, "Post deleted.")
            return redirect("superuser-dashboard")

    posts = Post.objects.select_related("author").all()
    return render(
        request,
        "superuser_dashboard.html",
        {
            "form": form,
            "post_form": post_form,
            "posts": posts,
            "businesses": businesses,
        },
    )


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


def _role_choices_for_profile(profile):
    if profile.role == UserProfile.ROLE_EMPLOYER:
        return UserProfile.ROLE_CHOICES
    return [choice for choice in UserProfile.ROLE_CHOICES if choice[0] == UserProfile.ROLE_EMPLOYEE]


@login_required
def role_select(request):
    profile, _ = UserProfile.objects.select_related("business").get_or_create(user=request.user)
    if request.user.is_superuser:
        return redirect("superuser-dashboard")
    if not profile.business_id:
        messages.error(request, "Your account is not linked to a business. Contact the administrator.")
        return redirect("logout")
    business = profile.business
    if business.sync_payment_status():
        business.save(update_fields=["payment_status"])
    if business.payment_status == Business.PAYMENT_OVERDUE:
        messages.error(
            request,
            "Your subscription payment is overdue. Contact admin to restore access.",
        )
        return redirect("logout")
    if not profile.is_business_active or not business.is_active:
        messages.error(
            request,
            "Your business account has been deactivated. Contact admin.",
        )
        return redirect("logout")

    role_choices = _role_choices_for_profile(profile)
    if request.method == "POST":
        form = RoleSelectionForm(request.POST)
        form.fields["role"].choices = role_choices
        if form.is_valid():
            selected_role = form.cleaned_data["role"]
            employer_password = form.cleaned_data.get("employer_password", "")
            if selected_role == UserProfile.ROLE_EMPLOYER and profile.role != UserProfile.ROLE_EMPLOYER:
                messages.error(request, "Your account is not registered as an employer.")
                return redirect("role-select")
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
        default_role = profile.role or UserProfile.ROLE_EMPLOYEE
        if default_role not in {choice[0] for choice in role_choices}:
            default_role = UserProfile.ROLE_EMPLOYEE
        form = RoleSelectionForm(initial={"role": default_role})
        form.fields["role"].choices = role_choices
    is_employer_account = profile.role == UserProfile.ROLE_EMPLOYER
    return render(
        request,
        "role_select.html",
        {"form": form, "is_employer_account": is_employer_account},
    )


def _can_access_role(request, role):
    user = request.user
    if not user.is_authenticated or user.is_superuser:
        return False
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        return False
    if not profile.business_id or not profile.is_business_active or not profile.business.is_active:
        return False
    business = profile.business
    if business.sync_payment_status():
        business.save(update_fields=["payment_status"])
    if business.payment_status == Business.PAYMENT_OVERDUE:
        return False
    session_role = request.session.get("active_role")
    if not session_role:
        return False
    if role == UserProfile.ROLE_EMPLOYER:
        return session_role == UserProfile.ROLE_EMPLOYER
    if role == UserProfile.ROLE_EMPLOYEE:
        if session_role == UserProfile.ROLE_EMPLOYEE:
            return True
        return (
            session_role == UserProfile.ROLE_EMPLOYER
            and profile.role == UserProfile.ROLE_EMPLOYER
        )
    return False


def _dashboard_switch_context(request):
    profile = request.user.profile
    session_role = request.session.get("active_role")
    is_employer_account = profile.role == UserProfile.ROLE_EMPLOYER
    return {
        "can_switch_to_employee": is_employer_account and session_role == UserProfile.ROLE_EMPLOYER,
        "can_switch_to_employer": session_role == UserProfile.ROLE_EMPLOYER,
    }


def _record_sale_with_stock(business, item, quantity, user, payment_method, mpesa_amount_sent):
    assert_business_access(user, business)
    if item.business_id != business.pk:
        raise TenantAccessError("Item does not belong to your business.")
    with transaction.atomic():
        rows_updated = (
            Item.objects.for_business(business)
            .filter(pk=item.pk, current_quantity__gte=quantity)
            .update(current_quantity=F("current_quantity") - quantity)
        )
        if rows_updated == 0:
            return None
        Item.objects.for_business(business).filter(pk=item.pk).update(
            stock_qty=F("current_quantity")
        )
        item.refresh_from_db(fields=["unit_price"])
        sale = Sale.objects.create(
            business=business,
            item=item,
            quantity=quantity,
            sold_by=user,
            payment_method=payment_method,
            mpesa_amount_sent=mpesa_amount_sent,
            total_amount=Decimal(quantity) * item.unit_price,
        )
        ensure_business_year_start(user, sale.sold_at)
        return sale


def _stock_insights_queryset(business):
    return (
        Item.objects.for_business(business)
        .exclude(status=Item.STATUS_DELETED)
        .annotate(total_sold=Coalesce(Sum("sales__quantity"), 0))
        .order_by("name")
    )


@login_required
def employer_dashboard(request):
    if not _can_access_role(request, UserProfile.ROLE_EMPLOYER):
        return redirect("role-select")
    business = _require_tenant_business(request)
    if business is None:
        return redirect("logout")

    items = (
        scoped_qs(Item, request.user)
        .exclude(status=Item.STATUS_DELETED)
        .order_by("-created_at")
    )
    active_items = scoped_qs(Item, request.user).filter(
        status=Item.STATUS_ACTIVE,
        current_quantity__gt=0,
    ).order_by("name")
    item_form = ItemForm()
    sale_form = SaleForm(business=business)
    ai_data = ai_item_suggestions(request.user)
    ensure_weekly_ml_reports(request.user)
    weekly_reports = weekly_ml_report_history(request.user)
    latest_weekly_report = weekly_reports.first()
    if latest_weekly_report:
        ml_analysis_rows = latest_weekly_report.report_data.get("rows", [])
    else:
        ml_analysis_rows = []
    daily_sales, daily_revenue, daily_units = sales_summary(request.user, "daily")
    daily_profit = profit_summary(request.user, "daily")
    expenses = scoped_qs(Expense, request.user).order_by("-expense_date", "-created_at")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add_item":
            item_form = ItemForm(request.POST)
            if item_form.is_valid():
                item = item_form.save(commit=False)
                item.business = business
                item.created_by = request.user
                item.name = item.name.strip()

                existing_item = Item.objects.for_business(business).filter(
                    name__iexact=item.name
                ).first()

                if existing_item is None:
                    item.current_quantity = item.initial_quantity
                    item.stock_qty = item.initial_quantity
                    item.save()
                    messages.success(request, "Item added successfully.")
                else:
                    added_quantity = item.initial_quantity
                    update_fields = {
                        "unit_price": item.unit_price,
                    }
                    if item.category:
                        update_fields["category"] = item.category

                    if added_quantity:
                        update_fields.update(
                            {
                                "current_quantity": F("current_quantity") + added_quantity,
                                "initial_quantity": F("initial_quantity") + added_quantity,
                                "stock_qty": F("stock_qty") + added_quantity,
                            }
                        )

                    with transaction.atomic():
                        Item.objects.for_business(business).filter(pk=existing_item.pk).update(
                            **update_fields
                        )
                    messages.success(request, "Existing item stock increased successfully.")

                return redirect("employer-dashboard")

        elif action == "record_sale":
            sale_form = SaleForm(request.POST, business=business)
            if sale_form.is_valid():
                sale = sale_form.save(commit=False)
                recorded = _record_sale_with_stock(
                    business=business,
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

        elif action == "update_item_price":
            item = get_tenant_object(Item, request.user, pk=request.POST.get("item_id"))
            try:
                new_price = Decimal(request.POST.get("price"))
                if new_price < 0:
                    messages.error(request, "Price cannot be negative.")
                    return redirect("employer-dashboard")
                item.unit_price = new_price
                item.save(update_fields=["unit_price"])
                messages.success(request, f"Price for {item.name} updated to {new_price}.")
            except (ValueError, TypeError):
                messages.error(request, "Invalid price format.")
            return redirect("employer-dashboard")

        elif action == "delete_item":
            item = get_tenant_object(Item, request.user, pk=request.POST.get("item_id"))
            item.status = Item.STATUS_DELETED
            item.save(update_fields=["status"])
            messages.info(request, f"Item {item.name} marked as {item.status}.")
            return redirect("employer-dashboard")

        elif action == "change_password":
            profile = request.user.profile
            old_password = request.POST.get("old_password", "")
            new_login_password1 = request.POST.get("new_login_password1", "")
            new_login_password2 = request.POST.get("new_login_password2", "")
            new_employer_password1 = request.POST.get("new_employer_password1", "")
            new_employer_password2 = request.POST.get("new_employer_password2", "")

            if not request.user.check_password(old_password):
                messages.error(request, "Current password is incorrect.")
                return redirect("employer-dashboard")

            changed_anything = False
            if new_login_password1 or new_login_password2:
                if new_login_password1 != new_login_password2:
                    messages.error(request, "New login passwords do not match.")
                    return redirect("employer-dashboard")
                try:
                    validate_password(new_login_password1, request.user)
                except ValidationError as exc:
                    messages.error(request, "; ".join(exc.messages))
                    return redirect("employer-dashboard")
                request.user.set_password(new_login_password1)
                request.user.save(update_fields=["password"])
                changed_anything = True

            if new_employer_password1 or new_employer_password2:
                if new_employer_password1 != new_employer_password2:
                    messages.error(request, "New employer passwords do not match.")
                    return redirect("employer-dashboard")
                if len(new_employer_password1) < 8:
                    messages.error(request, "Employer password must be at least 8 characters.")
                    return redirect("employer-dashboard")
                profile.set_employer_password(new_employer_password1)
                profile.save(update_fields=["employer_password_hash"])
                changed_anything = True

            if changed_anything:
                messages.success(request, "Your password(s) were updated successfully.")
            else:
                messages.info(request, "No password changes were provided.")
            return redirect("employer-dashboard")

    stock_insights = _stock_insights_queryset(business)
    context = {
        **_dashboard_switch_context(request),
        "items": items,
        "item_form": item_form,
        "sale_form": sale_form,
        "ai_data": ai_data,
        "ml_analysis_rows": ml_analysis_rows,
        "weekly_ml_reports": weekly_reports,
        "latest_weekly_report": latest_weekly_report,
        "daily_sales": daily_sales,
        "daily_revenue": daily_revenue,
        "daily_units": daily_units,
        "daily_expenses": daily_profit["expenses"],
        "daily_net_profit": daily_profit["net_profit"],
        "expenses": expenses,
        "stock_insights": stock_insights,
    }
    return render(request, "employer_dashboard.html", context)


def _daily_pdf_context(user):
    business = get_user_business(user)
    sales, total_revenue, total_units = sales_summary(user, "daily")
    daily_expenses, total_expenses = expenses_summary(user, "daily")
    daily_profit = profit_summary(user, "daily")
    report_date = timezone.localtime(timezone.now()).date()
    return {
        "business_name": business.name,
        "report_date": report_date,
        "sales": sales.order_by("sold_at"),
        "total_revenue": total_revenue,
        "total_units": total_units,
        "expenses": daily_expenses.order_by("-created_at"),
        "total_expenses": total_expenses,
        "net_profit": daily_profit["net_profit"],
    }


def _period_pdf_context(user, period):
    business = get_user_business(user)
    profit_report = period_profit_report(user, period)
    period_expenses, _ = expenses_summary(user, period)
    return {
        "business_name": business.name,
        "report_date": timezone.localtime(timezone.now()).date(),
        "revenue_report": profit_report,
        "period_expenses": period_expenses.order_by("-expense_date", "-created_at"),
        "business": business,
    }


def _pdf_download_response(pdf_bytes, filename):
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def daily_sales_pdf(request):
    if not _can_access_role(request, UserProfile.ROLE_EMPLOYER):
        return redirect("role-select")
    business = _require_tenant_business(request)
    if business is None:
        return redirect("logout")

    try:
        pdf_bytes = build_daily_sales_pdf(_daily_pdf_context(request.user))
    except PDFGenerationError:
        messages.error(request, "Could not generate PDF. Please try again.")
        return redirect("employer-dashboard")

    report_date = timezone.localtime(timezone.now()).date()
    business_slug = slugify(business.name) or "business"
    filename = f"daily-sales-{report_date}-{business_slug}.pdf"
    return _pdf_download_response(pdf_bytes, filename)


@login_required
def report_pdf(request, period):
    if not _can_access_role(request, UserProfile.ROLE_EMPLOYER):
        return redirect("role-select")
    business = _require_tenant_business(request)
    if business is None:
        return redirect("logout")
    if period not in {"daily", "weekly", "monthly", "yearly"}:
        return redirect("reports", period="daily")

    report_date = timezone.localtime(timezone.now()).date()
    business_slug = slugify(business.name) or "business"

    try:
        if period == "daily":
            pdf_bytes = build_daily_sales_pdf(_daily_pdf_context(request.user))
            filename = f"daily-sales-{report_date}-{business_slug}.pdf"
        else:
            pdf_bytes = build_period_summary_pdf(
                period, _period_pdf_context(request.user, period)
            )
            filename = f"{period}-report-{report_date}-{business_slug}.pdf"
    except PDFGenerationError:
        messages.error(request, "Could not generate PDF. Please try again.")
        return redirect("reports", period=period)

    return _pdf_download_response(pdf_bytes, filename)


@login_required
def weekly_ml_report_pdf(request, report_id):
    if not _can_access_role(request, UserProfile.ROLE_EMPLOYER):
        return redirect("role-select")
    business = _require_tenant_business(request)
    if business is None:
        return redirect("logout")

    report = get_object_or_404(
        weekly_ml_report_history(request.user).filter(pk=report_id)
    )

    try:
        pdf_bytes = build_weekly_ml_report_pdf(report)
    except PDFGenerationError:
        messages.error(request, "Could not generate PDF. Please try again.")
        return redirect("employer-dashboard")

    filename = f"weekly-ml-report-{report.week_start_date}-{slugify(business.name)}.pdf"
    return _pdf_download_response(pdf_bytes, filename)


@login_required
def reports_view(request, period):
    if not _can_access_role(request, UserProfile.ROLE_EMPLOYER):
        return redirect("role-select")
    business = _require_tenant_business(request)
    if business is None:
        return redirect("logout")
    if period not in {"daily", "weekly", "monthly", "yearly"}:
        period = "daily"

    if period == "daily":
        sales, revenue, units = sales_summary(request.user, period)
        daily_profit = profit_summary(request.user, period)
        daily_expenses, _ = expenses_summary(request.user, period)
        ml_analysis_rows = ml_sales_analysis_table(request.user, period)
        return render(
            request,
            "reports.html",
            {
                "period": period,
                "sales": sales,
                "revenue": revenue,
                "units": units,
                "expenses": daily_profit["expenses"],
                "net_profit": daily_profit["net_profit"],
                "daily_expenses": daily_expenses,
                "ml_analysis_rows": ml_analysis_rows,
            },
        )

    profit_report = period_profit_report(request.user, period)
    period_expenses, _ = expenses_summary(request.user, period)
    return render(
        request,
        "reports.html",
        {
            "period": period,
            "revenue_report": profit_report,
            "period_expenses": period_expenses,
            "business": business,
        },
    )


@login_required
def employee_dashboard(request):
    if not _can_access_role(request, UserProfile.ROLE_EMPLOYEE):
        return redirect("role-select")
    business = _require_tenant_business(request)
    if business is None:
        return redirect("logout")

    active_items = scoped_qs(Item, request.user).filter(
        status=Item.STATUS_ACTIVE,
        current_quantity__gt=0,
    ).order_by("name")
    sale_form = SaleForm(business=business)
    expense_form = ExpenseForm()

    if request.method == "POST":
        if request.POST.get("action") == "add_expense":
            expense_form = ExpenseForm(request.POST)
            if expense_form.is_valid():
                expense = expense_form.save(commit=False)
                expense.business = business
                expense.recorded_by = request.user
                expense.save()
                messages.success(request, "Expense recorded successfully.")
                return redirect("employee-dashboard")
        else:
            sale_form = SaleForm(request.POST, business=business)
            if sale_form.is_valid():
                sale = sale_form.save(commit=False)
                recorded = _record_sale_with_stock(
                    business=business,
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

    daily_sales, daily_revenue, daily_units = sales_summary(request.user, "daily")
    daily_profit = profit_summary(request.user, "daily")
    today = timezone.localdate()
    my_daily_expenses = (
        scoped_qs(Expense, request.user)
        .filter(recorded_by=request.user, expense_date=today)
        .order_by("-created_at")
    )
    my_daily_sales = daily_sales.filter(sold_by=request.user)
    my_daily_units = my_daily_sales.aggregate(total=Sum("quantity"))["total"] or 0
    my_daily_revenue = _quantize_money(
        my_daily_sales.aggregate(total=Sum("total_amount"))["total"]
    )
    item_prices = {str(item.pk): str(item.unit_price) for item in active_items}
    item_stock = {
        str(item.pk): {
            "remaining": item.current_quantity,
            "initial": item.initial_quantity,
        }
        for item in active_items
    }
    return render(
        request,
        "employee_dashboard.html",
        {
            **_dashboard_switch_context(request),
            "sale_form": sale_form,
            "expense_form": expense_form,
            "active_items": active_items,
            "daily_sales": daily_sales,
            "daily_revenue": daily_revenue,
            "daily_units": daily_units,
            "daily_expenses": daily_profit["expenses"],
            "daily_net_profit": daily_profit["net_profit"],
            "my_daily_units": my_daily_units,
            "my_daily_revenue": my_daily_revenue,
            "my_daily_expenses": my_daily_expenses,
            "item_prices": item_prices,
            "item_stock": item_stock,
        },
    )


@login_required
def sales_analytics_api(request):
    if not _can_access_role(request, UserProfile.ROLE_EMPLOYER):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    business = _require_tenant_business(request)
    if business is None:
        return JsonResponse({"detail": "Forbidden"}, status=403)
    insights = list(_stock_insights_queryset(business).values("name", "total_sold"))
    return JsonResponse({"items": insights})


@login_required
def stock_insights_api(request):
    if not _can_access_role(request, UserProfile.ROLE_EMPLOYER):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    business = _require_tenant_business(request)
    if business is None:
        return JsonResponse({"detail": "Forbidden"}, status=403)
    insights = list(
        _stock_insights_queryset(business).values("name", "current_quantity", "total_sold")
    )
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
        "total_businesses": Business.objects.count(),
    }
    return JsonResponse(payload)

def create_superuser(request):
    if not User.objects.filter(username="admin").exists():
        User.objects.create_superuser(
            username="hezekiah254",
            email="hezekiahmonyancha60@gmail.com",
            password="S!mpl3 B0y.hezekiah254"
        )
        return HttpResponse("Superuser created")
    return HttpResponse("Already exists")
