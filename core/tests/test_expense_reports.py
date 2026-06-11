from datetime import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Business, Expense, Item, Sale, UserProfile
from core.services import (
    ensure_business_year_start,
    expenses_summary,
    profit_summary,
    weekly_profit_report,
    yearly_profit_report,
)


class ExpenseReportTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Expense Shop")
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
            name="Soap",
            unit_price=Decimal("100.00"),
            initial_quantity=20,
            current_quantity=20,
            stock_qty=20,
            created_by=self.employer,
        )
        self.today = timezone.localdate()

    def _record_sale(self, amount, when=None):
        sale = Sale.objects.create(
            business=self.business,
            item=self.item,
            quantity=1,
            sold_by=self.employer,
            payment_method=Sale.PAYMENT_CASH,
            total_amount=amount,
        )
        if when is not None:
            Sale.objects.filter(pk=sale.pk).update(sold_at=when)
            sale.refresh_from_db()
        ensure_business_year_start(self.business, sale.sold_at)
        return sale

    def _record_expense(self, amount, reason="Supplies", recorded_by=None, expense_date=None):
        return Expense.objects.create(
            business=self.business,
            amount=amount,
            reason=reason,
            expense_date=expense_date or self.today,
            recorded_by=recorded_by or self.employee,
        )

    def test_profit_summary_subtracts_expenses_from_revenue(self):
        self._record_sale(Decimal("500.00"))
        self._record_expense(Decimal("120.00"))
        summary = profit_summary(self.business, "daily")
        self.assertEqual(summary["revenue"], Decimal("500.00"))
        self.assertEqual(summary["expenses"], Decimal("120.00"))
        self.assertEqual(summary["net_profit"], Decimal("380.00"))

    def test_weekly_profit_report_includes_expense_totals(self):
        self._record_sale(Decimal("200.00"))
        self._record_expense(Decimal("50.00"))
        report = weekly_profit_report(self.business)
        self.assertEqual(report["total_expenses"], Decimal("50.00"))
        self.assertEqual(report["net_profit"], Decimal("150.00"))
        self.assertIn("expenses", report["rows"][0])

    def test_yearly_expenses_summary_covers_business_year_window(self):
        month_start = self.today.replace(day=1)
        if month_start.month == 1:
            old_month = month_start.replace(year=month_start.year - 1, month=12)
        else:
            old_month = month_start.replace(month=month_start.month - 1)
        first_sale_at = timezone.make_aware(datetime.combine(old_month, datetime.min.time()))
        self._record_sale(Decimal("1.00"), when=first_sale_at)
        self._record_expense(Decimal("30.00"), expense_date=old_month)
        self._record_expense(Decimal("10.00"))
        expenses, total = expenses_summary(self.business, "yearly")
        self.assertEqual(total, Decimal("40.00"))
        self.assertEqual(expenses.count(), 2)

    def test_employee_can_record_expense(self):
        client = Client()
        client.login(username="employee", password="pass12345")
        session = client.session
        session["active_role"] = UserProfile.ROLE_EMPLOYEE
        session.save()

        response = client.post(
            reverse("employee-dashboard"),
            {
                "action": "add_expense",
                "amount": "75.50",
                "reason": "Transport",
                "expense_date": self.today.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 302)
        expense = Expense.objects.get(business=self.business)
        self.assertEqual(expense.amount, Decimal("75.50"))
        self.assertEqual(expense.recorded_by, self.employee)

    def test_daily_report_page_lists_expenses_and_net_profit(self):
        self._record_sale(Decimal("300.00"))
        self._record_expense(Decimal("80.00"), reason="Cleaning")
        client = Client()
        client.login(username="employer", password="pass12345")
        session = client.session
        session["active_role"] = UserProfile.ROLE_EMPLOYER
        session.save()

        response = client.get(reverse("reports", kwargs={"period": "daily"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total Expenses (KES)")
        self.assertContains(response, "80.00")
        self.assertContains(response, "Final Amount (KES)")
        self.assertContains(response, "Cleaning")
        content = response.content.decode()
        self.assertIn("220", content)

    def test_weekly_report_page_lists_period_expenses(self):
        self._record_expense(Decimal("45.00"), reason="Fuel")
        client = Client()
        client.login(username="employer", password="pass12345")
        session = client.session
        session["active_role"] = UserProfile.ROLE_EMPLOYER
        session.save()

        response = client.get(reverse("reports", kwargs={"period": "weekly"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Expenses This Week")
        self.assertContains(response, "Fuel")
        self.assertContains(response, "45.00")

    def test_daily_pdf_includes_expense_totals(self):
        self._record_sale(Decimal("150.00"))
        self._record_expense(Decimal("25.00"), reason="Snacks")
        client = Client()
        client.login(username="employer", password="pass12345")
        session = client.session
        session["active_role"] = UserProfile.ROLE_EMPLOYER
        session.save()

        response = client.get(reverse("daily-sales-pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(b"Expenses Today", response.content)

    def test_yearly_profit_report_aggregates_expenses(self):
        self._record_sale(Decimal("1000.00"))
        self._record_expense(Decimal("200.00"))
        report = yearly_profit_report(self.business)
        self.assertEqual(report["total_expenses"], Decimal("200.00"))
        self.assertEqual(report["net_profit"], Decimal("800.00"))
