from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import Business, Item, ItemReport, Sale, UserProfile


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


class SaleForm(forms.ModelForm):
    class Meta:
        model = Sale
        fields = ["item", "quantity", "payment_method", "mpesa_amount_sent"]

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        if business is not None:
            self.fields["item"].queryset = Item.objects.for_business(business).filter(
                status=Item.STATUS_ACTIVE,
                current_quantity__gt=0,
            )

    def clean_item(self):
        item = self.cleaned_data["item"]
        if self.business is not None and item.business_id != self.business.id:
            raise forms.ValidationError("Invalid item for your business.")
        return item


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
