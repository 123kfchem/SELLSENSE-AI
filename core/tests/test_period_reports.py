from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Business, Item, Sale, UserProfile
from core.services import monthly_revenue_report, weekly_revenue_report, yearly_revenue_report


class PeriodRevenueReportTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Report Shop")
        self.user = User.objects.create_user(username="employer", password="pass12345")
        UserProfile.objects.filter(user=self.user).update(
            business=self.business,
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
            created_by=self.user,
        )

    def _record_sale(self, amount, when=None):
        Sale.objects.create(
            business=self.business,
            item=self.item,
            quantity=1,
            sold_by=self.user,
            payment_method=Sale.PAYMENT_CASH,
            total_amount=amount,
            sold_at=when or timezone.now(),
        )

    def test_weekly_report_has_seven_days_and_total(self):
        self._record_sale(Decimal("50.00"))
        report = weekly_revenue_report(self.business)
        self.assertEqual(len(report["rows"]), 7)
        self.assertEqual(report["total_revenue"], Decimal("50.00"))
        self.assertNotIn("item", report["rows"][0])

    def test_monthly_and_yearly_reports_aggregate_revenue(self):
        self._record_sale(Decimal("120.00"))
        monthly = monthly_revenue_report(self.business)
        yearly = yearly_revenue_report(self.business)
        self.assertGreaterEqual(len(monthly["rows"]), 1)
        self.assertEqual(len(yearly["rows"]), 12)
        self.assertEqual(monthly["total_revenue"], Decimal("120.00"))
        self.assertEqual(yearly["total_revenue"], Decimal("120.00"))

    def test_weekly_report_page_hides_item_sales(self):
        self._record_sale(Decimal("75.00"))
        client = Client()
        client.login(username="employer", password="pass12345")
        session = client.session
        session["active_role"] = UserProfile.ROLE_EMPLOYER
        session.save()

        response = client.get(reverse("reports", kwargs={"period": "weekly"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total Weekly Revenue")
        self.assertContains(response, "75.00")
        self.assertNotContains(response, "Soap")
