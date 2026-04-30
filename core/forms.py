from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Item, ItemReport, Sale, UserProfile


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


class BusinessProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["role", "business_name", "phone_number", "location", "is_business_active"]
