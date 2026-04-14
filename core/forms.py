from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Item, ItemReport, Sale, UserProfile


class RoleSelectionForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["role"]


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ["name", "category", "unit_price", "stock_qty"]


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
            "password1",
            "password2",
        ]


class BusinessProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["role", "business_name", "phone_number", "location", "is_business_active"]
