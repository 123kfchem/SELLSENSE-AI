from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Business, Item, Sale, UserProfile


class DailySalesPDFTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.business_a = Business.objects.create(name="Shop A")
        self.business_b = Business.objects.create(name="Shop B")

        self.employer_a = User.objects.create_user(username="employer_a", password="pass12345")
        self.employer_b = User.objects.create_user(username="employer_b", password="pass12345")

        UserProfile.objects.filter(user=self.employer_a).update(
            business=self.business_a,
            role=UserProfile.ROLE_EMPLOYER,
            is_business_active=True,
        )
        UserProfile.objects.filter(user=self.employer_b).update(
            business=self.business_b,
            role=UserProfile.ROLE_EMPLOYER,
            is_business_active=True,
        )

        self.item_a = Item.objects.create(
            business=self.business_a,
            name="Milk",
            unit_price=Decimal("50.00"),
            initial_quantity=10,
            current_quantity=9,
            stock_qty=9,
            created_by=self.employer_a,
        )
        self.item_b = Item.objects.create(
            business=self.business_b,
            name="Bread",
            unit_price=Decimal("30.00"),
            initial_quantity=10,
            current_quantity=10,
            stock_qty=10,
            created_by=self.employer_b,
        )

        Sale.objects.create(
            business=self.business_a,
            item=self.item_a,
            quantity=1,
            sold_by=self.employer_a,
            payment_method=Sale.PAYMENT_CASH,
            total_amount=Decimal("50.00"),
            sold_at=timezone.now(),
        )
        Sale.objects.create(
            business=self.business_b,
            item=self.item_b,
            quantity=2,
            sold_by=self.employer_b,
            payment_method=Sale.PAYMENT_CASH,
            total_amount=Decimal("60.00"),
            sold_at=timezone.now(),
        )

    def _login_as_employer(self, username):
        self.client.login(username=username, password="pass12345")
        session = self.client.session
        session["active_role"] = UserProfile.ROLE_EMPLOYER
        session.save()

    def test_employer_can_download_daily_sales_pdf(self):
        self._login_as_employer("employer_a")
        response = self.client.get(reverse("daily-sales-pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_pdf_only_includes_own_business_sales(self):
        self._login_as_employer("employer_a")
        response = self.client.get(reverse("daily-sales-pdf"))
        self.assertIn(b"Shop A", response.content)
        self.assertNotIn(b"Shop B", response.content)

    def test_employee_cannot_access_pdf(self):
        employee = User.objects.create_user(username="employee_a", password="pass12345")
        UserProfile.objects.filter(user=employee).update(
            business=self.business_a,
            role=UserProfile.ROLE_EMPLOYEE,
            is_business_active=True,
        )
        self.client.login(username="employee_a", password="pass12345")
        session = self.client.session
        session["active_role"] = UserProfile.ROLE_EMPLOYEE
        session.save()

        response = self.client.get(reverse("daily-sales-pdf"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("role-select"), response.url)
