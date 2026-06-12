from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Business, Expense, Item, Sale, UserProfile
from core.services import ensure_business_year_start


class PeriodReportPDFTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.business = Business.objects.create(name="PDF Shop")
        self.other_business = Business.objects.create(name="Other Shop")
        self.employer = User.objects.create_user(username="employer", password="pass12345")
        self.other_employer = User.objects.create_user(username="other", password="pass12345")

        UserProfile.objects.filter(user=self.employer).update(
            business=self.business,
            role=UserProfile.ROLE_EMPLOYER,
            is_business_active=True,
        )
        UserProfile.objects.filter(user=self.other_employer).update(
            business=self.other_business,
            role=UserProfile.ROLE_EMPLOYER,
            is_business_active=True,
        )

        self.item = Item.objects.create(
            business=self.business,
            name="Soap",
            unit_price=Decimal("100.00"),
            initial_quantity=20,
            current_quantity=20,
            stock_qty=20,
            created_by=self.employer,
        )
        self.other_item = Item.objects.create(
            business=self.other_business,
            name="Bread",
            unit_price=Decimal("50.00"),
            initial_quantity=10,
            current_quantity=10,
            stock_qty=10,
            created_by=self.other_employer,
        )

        sale = Sale.objects.create(
            business=self.business,
            item=self.item,
            quantity=1,
            sold_by=self.employer,
            payment_method=Sale.PAYMENT_CASH,
            total_amount=Decimal("100.00"),
            sold_at=timezone.now(),
        )
        ensure_business_year_start(self.employer, sale.sold_at)

        Expense.objects.create(
            business=self.business,
            amount=Decimal("25.00"),
            reason="Supplies",
            expense_date=timezone.localdate(),
            recorded_by=self.employer,
        )

        Sale.objects.create(
            business=self.other_business,
            item=self.other_item,
            quantity=1,
            sold_by=self.other_employer,
            payment_method=Sale.PAYMENT_CASH,
            total_amount=Decimal("50.00"),
            sold_at=timezone.now(),
        )

    def _login_as_employer(self, username="employer"):
        self.client.login(username=username, password="pass12345")
        session = self.client.session
        session["active_role"] = UserProfile.ROLE_EMPLOYER
        session.save()

    def _assert_valid_pdf(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_employer_can_download_weekly_report_pdf(self):
        self._login_as_employer()
        response = self.client.get(reverse("report-pdf", kwargs={"period": "weekly"}))
        self._assert_valid_pdf(response)
        self.assertIn(b"PDF Shop", response.content)
        self.assertIn(b"Weekly", response.content)

    def test_employer_can_download_monthly_report_pdf(self):
        self._login_as_employer()
        response = self.client.get(reverse("report-pdf", kwargs={"period": "monthly"}))
        self._assert_valid_pdf(response)
        self.assertIn(b"Monthly", response.content)

    def test_employer_can_download_yearly_report_pdf(self):
        self._login_as_employer()
        response = self.client.get(reverse("report-pdf", kwargs={"period": "yearly"}))
        self._assert_valid_pdf(response)
        self.assertIn(b"Yearly", response.content)

    def test_daily_report_pdf_route_matches_daily_sales_pdf(self):
        self._login_as_employer()
        response = self.client.get(reverse("report-pdf", kwargs={"period": "daily"}))
        self._assert_valid_pdf(response)
        self.assertIn(b"Daily Sales Report", response.content)

    def test_pdf_only_includes_own_business_data(self):
        self._login_as_employer()
        response = self.client.get(reverse("report-pdf", kwargs={"period": "weekly"}))
        self.assertIn(b"PDF Shop", response.content)
        self.assertNotIn(b"Other Shop", response.content)

    def test_employee_cannot_access_period_report_pdf(self):
        employee = User.objects.create_user(username="employee", password="pass12345")
        UserProfile.objects.filter(user=employee).update(
            business=self.business,
            role=UserProfile.ROLE_EMPLOYEE,
            is_business_active=True,
        )
        self.client.login(username="employee", password="pass12345")
        session = self.client.session
        session["active_role"] = UserProfile.ROLE_EMPLOYEE
        session.save()

        response = self.client.get(reverse("report-pdf", kwargs={"period": "weekly"}))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("role-select"), response.url)
