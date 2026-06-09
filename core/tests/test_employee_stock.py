from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Business, Item, Sale, UserProfile


class EmployeeStockDeductionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.business = Business.objects.create(name="Stock Test Business")
        self.employer = User.objects.create_user(username="employer", password="pass12345")
        self.employee = User.objects.create_user(username="employee", password="pass12345")

        UserProfile.objects.filter(user=self.employer).update(
            business=self.business,
            role=UserProfile.ROLE_EMPLOYER,
            is_business_active=True,
        )
        UserProfile.objects.filter(user=self.employee).update(
            business=self.business,
            role=UserProfile.ROLE_EMPLOYEE,
            is_business_active=True,
        )

        self.item = Item.objects.create(
            business=self.business,
            name="Test Product",
            unit_price=Decimal("100.00"),
            initial_quantity=10,
            current_quantity=10,
            stock_qty=10,
            created_by=self.employer,
        )

    def _login_as_employee(self):
        self.client.login(username="employee", password="pass12345")
        session = self.client.session
        session["active_role"] = UserProfile.ROLE_EMPLOYEE
        session.save()

    def test_employee_sale_reduces_remaining_stock(self):
        self._login_as_employee()
        response = self.client.post(
            reverse("employee-dashboard"),
            {
                "item": self.item.pk,
                "quantity": 3,
                "payment_method": Sale.PAYMENT_CASH,
            },
        )
        self.assertEqual(response.status_code, 302)

        self.item.refresh_from_db()
        self.assertEqual(self.item.initial_quantity, 10)
        self.assertEqual(self.item.current_quantity, 7)
        self.assertEqual(self.item.stock_qty, 7)
        self.assertEqual(Sale.objects.for_business(self.business).count(), 1)

    def test_employee_cannot_sell_more_than_remaining_stock(self):
        self._login_as_employee()
        response = self.client.post(
            reverse("employee-dashboard"),
            {
                "item": self.item.pk,
                "quantity": 15,
                "payment_method": Sale.PAYMENT_CASH,
            },
        )
        self.assertEqual(response.status_code, 200)

        self.item.refresh_from_db()
        self.assertEqual(self.item.current_quantity, 10)
        self.assertEqual(Sale.objects.for_business(self.business).count(), 0)
