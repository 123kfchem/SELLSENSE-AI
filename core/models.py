from decimal import Decimal

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.db import models


class Business(models.Model):
    name = models.CharField(max_length=180)
    phone_number = models.CharField(max_length=30, blank=True)
    location = models.CharField(max_length=180, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "businesses"

    def __str__(self):
        return self.name


class TenantQuerySet(models.QuerySet):
    def for_business(self, business):
        if business is None:
            return self.none()
        return self.filter(business=business)


class TenantManager(models.Manager):
    def get_queryset(self):
        return TenantQuerySet(self.model, using=self._db)

    def for_business(self, business):
        return self.get_queryset().for_business(business)


class TenantModel(models.Model):
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="%(class)ss",
    )

    objects = TenantManager()

    class Meta:
        abstract = True


class UserProfile(models.Model):
    ROLE_EMPLOYER = "employer"
    ROLE_EMPLOYEE = "employee"
    ROLE_CHOICES = [
        (ROLE_EMPLOYER, "Employer"),
        (ROLE_EMPLOYEE, "Employee"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="members",
        null=True,
        blank=True,
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, null=True, blank=True)
    is_business_active = models.BooleanField(default=True)
    employer_password_hash = models.CharField(max_length=255, blank=True)

    def __str__(self):
        label = self.business.name if self.business_id else "unassigned"
        return f"{self.user.username} - {self.role or 'unassigned'} @ {label}"

    @property
    def business_name(self):
        return self.business.name if self.business_id else ""

    @property
    def phone_number(self):
        return self.business.phone_number if self.business_id else ""

    @property
    def location(self):
        return self.business.location if self.business_id else ""

    def set_employer_password(self, raw_password):
        self.employer_password_hash = make_password(raw_password or "")

    def check_employer_password(self, raw_password):
        if not self.employer_password_hash:
            return False
        return check_password(raw_password, self.employer_password_hash)


class Item(TenantModel):
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
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_items",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["business", "name"],
                name="uniq_item_name_per_business",
            ),
        ]

    def __str__(self):
        return self.name


class Sale(TenantModel):
    PAYMENT_CASH = "cash"
    PAYMENT_MPESA = "mpesa"
    PAYMENT_CHOICES = [
        (PAYMENT_CASH, "Cash"),
        (PAYMENT_MPESA, "M-Pesa"),
    ]

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="sales")
    quantity = models.PositiveIntegerField(default=1)
    sold_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sales",
    )
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES)
    mpesa_amount_sent = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    sold_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["business", "sold_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.item_id and not self.business_id:
            self.business_id = self.item.business_id
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


class ItemReport(TenantModel):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="reports")
    note = models.TextField()
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.item_id and not self.business_id:
            self.business_id = self.item.business_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Report for {self.item.name}"
