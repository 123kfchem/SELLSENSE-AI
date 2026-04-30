from decimal import Decimal
from django.contrib.auth.models import User
from django.contrib.auth.hashers import check_password, make_password
from django.db import models


class UserProfile(models.Model):
    ROLE_EMPLOYER = "employer"
    ROLE_EMPLOYEE = "employee"
    ROLE_CHOICES = [
        (ROLE_EMPLOYER, "Employer"),
        (ROLE_EMPLOYEE, "Employee"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, null=True, blank=True)
    business_name = models.CharField(max_length=180, blank=True)
    phone_number = models.CharField(max_length=30, blank=True)
    location = models.CharField(max_length=180, blank=True)
    is_business_active = models.BooleanField(default=True)
    employer_password_hash = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.role or 'unassigned'}"

    def set_employer_password(self, raw_password):
        self.employer_password_hash = make_password(raw_password or "")

    def check_employer_password(self, raw_password):
        if not self.employer_password_hash:
            return False
        return check_password(raw_password, self.employer_password_hash)


class Item(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_CANCELLED = "cancelled"
    STATUS_DELETED = "deleted"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_DELETED, "Deleted"),
    ]

    name = models.CharField(max_length=120)
    category = models.CharField(max_length=120, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    stock_qty = models.PositiveIntegerField(default=0)
    initial_quantity = models.PositiveIntegerField(default=0)
    current_quantity = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="created_items")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Sale(models.Model):
    PAYMENT_CASH = "cash"
    PAYMENT_MPESA = "mpesa"
    PAYMENT_CHOICES = [
        (PAYMENT_CASH, "Cash"),
        (PAYMENT_MPESA, "M-Pesa"),
    ]

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="sales")
    quantity = models.PositiveIntegerField(default=1)
    sold_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="sales")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES)
    mpesa_amount_sent = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    sold_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.total_amount:
            self.total_amount = Decimal(self.quantity) * self.item.unit_price
        if self.payment_method == self.PAYMENT_CASH:
            self.mpesa_amount_sent = None
        super().save(*args, **kwargs)

    @property
    def report_payment_value(self):
        if self.payment_method == self.PAYMENT_CASH:
            return "cash"
        return str(self.mpesa_amount_sent or self.total_amount)


class ItemReport(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="reports")
    note = models.TextField()
    reported_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report for {self.item.name}"
