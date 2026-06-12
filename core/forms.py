from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import Business, Expense, Item, ItemReport, Sale, UserProfile


class BusinessAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "business_inactive": (
            "Your business account has been deactivated. Contact admin."
        ),
    }

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.is_superuser:
            return
        profile = getattr(user, "profile", None)
        if profile is None or profile.business_id is None:
            raise ValidationError(
                "Your account is not linked to a business. Contact admin.",
                code="no_business",
            )
        business = profile.business
        if business.sync_payment_status():
            business.save(update_fields=["payment_status"])
        if business.payment_status == business.PAYMENT_OVERDUE:
            raise ValidationError(
                "Your subscription payment is overdue. Contact admin to restore access.",
                code="payment_overdue",
            )
        if not business.is_active or not profile.is_business_active:
            raise ValidationError(
                self.error_messages["business_inactive"],
                code="business_inactive",
            )


class RoleSelectionForm(forms.Form):
    role = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES)
    employer_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
        help_text="Required only when selecting Employer role.",
    )


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ["name", "category", "unit_price", "initial_quantity"]


class ItemReportForm(forms.ModelForm):
    class Meta:
        model = ItemReport
        fields = ["note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["amount", "reason", "expense_date"]
        widgets = {
            "reason": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Reason for this expense"}
            ),
            "expense_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.initial.get("expense_date"):
            from django.utils import timezone

            self.fields["expense_date"].initial = timezone.localdate()


class SaleForm(forms.ModelForm):
    class Meta:
        model = Sale
        fields = ["item", "quantity", "payment_method", "mpesa_amount_sent"]

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        if business is not None:
            queryset = Item.objects.for_business(business).filter(
                status=Item.STATUS_ACTIVE,
                current_quantity__gt=0,
            )
            self.fields["item"].queryset = queryset
            self.fields["item"].label_from_instance = (
                lambda obj: f"{obj.name} ({obj.current_quantity} remaining of {obj.initial_quantity})"
            )

    def clean_item(self):
        item = self.cleaned_data["item"]
        if self.business is not None and item.business_id != self.business.id:
            raise forms.ValidationError("Invalid item for your business.")
        return item

    def clean(self):
        cleaned_data = super().clean()
        item = cleaned_data.get("item")
        quantity = cleaned_data.get("quantity")
        if item and quantity:
            item.refresh_from_db(fields=["current_quantity", "initial_quantity", "name"])
            if quantity > item.current_quantity:
                raise ValidationError(
                    f"Only {item.current_quantity} unit(s) of {item.name} remain in stock."
                )
        return cleaned_data


class BusinessRegistrationForm(UserCreationForm):
    role = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES)
    email = forms.EmailField(required=False)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    business_name = forms.CharField(max_length=180, required=True)
    phone_number = forms.CharField(max_length=30, required=False)
    location = forms.CharField(max_length=180, required=False)
    employer_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Used when Employer role is selected at login.",
    )

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "business_name",
            "phone_number",
            "location",
            "employer_password",
            "password1",
            "password2",
        ]

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        employer_password = cleaned_data.get("employer_password")
        if role == UserProfile.ROLE_EMPLOYER and not employer_password:
            self.add_error("employer_password", "Employer password is required for Employer accounts.")
        return cleaned_data


class SuperuserPasswordResetForm(forms.Form):
    login_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Resets the business account login password.",
    )
    login_password_confirm = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    employer_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Resets the employer role password used at login.",
    )
    employer_password_confirm = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        if profile and profile.role != UserProfile.ROLE_EMPLOYER:
            del self.fields["employer_password"]
            del self.fields["employer_password_confirm"]

    def clean(self):
        cleaned_data = super().clean()
        login_password = cleaned_data.get("login_password", "")
        login_password_confirm = cleaned_data.get("login_password_confirm", "")
        employer_password = cleaned_data.get("employer_password", "")
        employer_password_confirm = cleaned_data.get("employer_password_confirm", "")

        if login_password or login_password_confirm:
            if login_password != login_password_confirm:
                raise ValidationError("Login passwords do not match.")
            validate_password(login_password, self.profile.user)

        if employer_password or employer_password_confirm:
            if self.profile.role != UserProfile.ROLE_EMPLOYER:
                raise ValidationError("Employer password can only be reset for employer accounts.")
            if employer_password != employer_password_confirm:
                raise ValidationError("Employer passwords do not match.")
            if len(employer_password) < 8:
                raise ValidationError("Employer password must be at least 8 characters.")

        if not login_password and not employer_password:
            raise ValidationError("Enter a new login password and/or employer password to reset.")

        return cleaned_data

    def save(self):
        profile = self.profile
        user = profile.user
        if self.cleaned_data.get("login_password"):
            user.set_password(self.cleaned_data["login_password"])
            user.save(update_fields=["password"])
        if self.cleaned_data.get("employer_password"):
            profile.set_employer_password(self.cleaned_data["employer_password"])
            profile.save(update_fields=["employer_password_hash"])
        return profile


class BusinessProfileUpdateForm(forms.Form):
    role = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES)
    business_name = forms.CharField(max_length=180)
    phone_number = forms.CharField(max_length=30, required=False)
    location = forms.CharField(max_length=180, required=False)
    is_business_active = forms.BooleanField(required=False)

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        if profile and profile.business_id:
            business = profile.business
            self.fields["business_name"].initial = business.name
            self.fields["phone_number"].initial = business.phone_number
            self.fields["location"].initial = business.location
            self.fields["role"].initial = profile.role
            self.fields["is_business_active"].initial = profile.is_business_active

    def save(self):
        profile = self.profile
        business = profile.business
        business.name = self.cleaned_data["business_name"]
        business.phone_number = self.cleaned_data.get("phone_number", "")
        business.location = self.cleaned_data.get("location", "")
        business.is_active = self.cleaned_data.get("is_business_active", False)
        business.save()
        profile.role = self.cleaned_data["role"]
        profile.is_business_active = self.cleaned_data.get("is_business_active", False)
        profile.save(update_fields=["role", "is_business_active"])
        return profile


class PaymentNoticeForm(forms.Form):
    amount_due = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        label="Amount due",
    )
    due_date = forms.DateField(
        label="Due date",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control form-control-sm"}),
    )
    payment_notice = forms.CharField(
        label="Message to business",
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "class": "form-control form-control-sm",
                "placeholder": "e.g. Pay via M-Pesa Paybill 123456 to continue using SellSense AI.",
            }
        ),
    )

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        if business and business.has_payment_notice:
            if business.amount_due is not None:
                self.fields["amount_due"].initial = business.amount_due
            if business.due_date:
                self.fields["due_date"].initial = business.due_date
            if business.payment_notice:
                self.fields["payment_notice"].initial = business.payment_notice

    def save(self):
        from django.utils import timezone

        business = Business.objects.get(pk=self.business.pk)
        business.amount_due = self.cleaned_data["amount_due"]
        business.due_date = self.cleaned_data["due_date"]
        business.payment_notice = self.cleaned_data["payment_notice"]
        business.payment_status = Business.PAYMENT_DUE
        business.notice_sent_at = timezone.now()
        business.save(
            update_fields=[
                "amount_due",
                "due_date",
                "payment_notice",
                "payment_status",
                "notice_sent_at",
            ]
        )
        return business


class ContactForm(forms.Form):
    full_name = forms.CharField(
        max_length=120,
        label="Full Name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "John Doe", "autocomplete": "name"}),
    )
    phone_number = forms.CharField(
        max_length=30,
        label="Phone Number",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "+254 700 000 000", "autocomplete": "tel"}),
    )
    email = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "you@company.com", "autocomplete": "email"}),
    )
    company_name = forms.CharField(
        max_length=120,
        required=False,
        label="Company Name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Your company (optional)", "autocomplete": "organization"}),
    )
    subject = forms.CharField(
        max_length=200,
        label="Subject",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "How can we help?"}),
    )
    message = forms.CharField(
        label="Message",
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 5, "placeholder": "Tell us more about your inquiry..."}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            for name, field in self.fields.items():
                if self.errors.get(name):
                    css = field.widget.attrs.get("class", "")
                    field.widget.attrs["class"] = f"{css} is-invalid".strip()
