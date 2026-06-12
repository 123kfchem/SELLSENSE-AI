from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Business, Item, Sale, UserProfile
from core.services import (
    _current_business_year_start,
    ensure_business_year_start,
    yearly_profit_report,
    yearly_revenue_report,
)


class BusinessYearReportTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Year Shop")
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
        sale = Sale.objects.create(
            business=self.business,
            item=self.item,
            quantity=1,
            sold_by=self.user,
            payment_method=Sale.PAYMENT_CASH,
            total_amount=amount,
        )
        if when is not None:
            Sale.objects.filter(pk=sale.pk).update(sold_at=when)
            sale.refresh_from_db()
        ensure_business_year_start(self.user, sale.sold_at)
        return sale

    def test_yearly_report_empty_before_first_sale(self):
        report = yearly_revenue_report(self.user)
        self.assertTrue(report["awaiting_first_sale"])
        self.assertEqual(report["rows"], [])
        self.assertEqual(report["total_revenue"], Decimal("0.00"))

    def test_first_sale_sets_business_year_start(self):
        first_sale_at = timezone.now()
        self._record_sale(Decimal("100.00"), when=first_sale_at)
        self.business.refresh_from_db()
        self.assertEqual(
            self.business.year_start_date,
            timezone.localtime(first_sale_at).date(),
        )

    def test_yearly_report_uses_twelve_months_from_first_sale(self):
        first_sale_at = timezone.localtime(timezone.now()).replace(
            month=3, day=15, hour=10, minute=0, second=0, microsecond=0
        )
        self._record_sale(Decimal("250.00"), when=first_sale_at)
        report = yearly_revenue_report(self.user)
        self.assertFalse(report["awaiting_first_sale"])
        self.assertEqual(len(report["rows"]), 12)
        self.assertEqual(report["rows"][0]["label"], first_sale_at.strftime("%B %Y"))
        self.assertEqual(report["total_revenue"], Decimal("250.00"))
        self.assertEqual(report["year_start_date"].month, 3)

    def test_yearly_report_advances_to_current_business_year(self):
        today = timezone.localdate()
        anchor = today - timedelta(days=400)
        self.business.year_start_date = anchor
        self.business.save(update_fields=["year_start_date"])
        report = yearly_revenue_report(self.user)
        expected_start = _current_business_year_start(anchor, today)
        self.assertEqual(report["year_start_date"], expected_start)

    def test_yearly_report_page_shows_business_year_message(self):
        client = Client()
        client.login(username="employer", password="pass12345")
        session = client.session
        session["active_role"] = UserProfile.ROLE_EMPLOYER
        session.save()

        response = client.get(reverse("reports", kwargs={"period": "yearly"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your business year starts when you record your first sale")

        self._record_sale(Decimal("90.00"))
        response = client.get(reverse("reports", kwargs={"period": "yearly"}))
        self.assertContains(response, "Business year:")
        self.assertContains(response, "based on your first sale")

    def test_yearly_profit_report_respects_business_year_window(self):
        self._record_sale(Decimal("1000.00"))
        report = yearly_profit_report(self.user)
        self.assertEqual(len(report["rows"]), 12)
        self.assertEqual(report["total_revenue"], Decimal("1000.00"))
