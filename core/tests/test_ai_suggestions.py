from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Business, Item, Sale, UserProfile
from core.services import (
    _build_ml_recommendation,
    _split_top_and_least_selling,
    ai_item_suggestions,
)


class SplitTopLeastSellingTests(TestCase):
    def test_three_products_splits_highest_from_rest(self):
        rows = [
            {"name": "Samsung A56", "total_qty": 5},
            {"name": "Trousers", "total_qty": 1},
            {"name": "IPHONE PROMAX 17", "total_qty": 1},
        ]
        top, least = _split_top_and_least_selling(rows)
        self.assertEqual([row["name"] for row in top], ["Samsung A56"])
        self.assertEqual(
            [row["name"] for row in least],
            ["IPHONE PROMAX 17", "Trousers"],
        )

    def test_lowest_tiers_go_to_least_not_top(self):
        rows = [
            {"name": "TROUSERS", "total_qty": 7},
            {"name": "Samsung A56", "total_qty": 5},
            {"name": "IPHONE PROMAX 17", "total_qty": 3},
            {"name": "Redmi note 14 pro", "total_qty": 3},
        ]
        top, least = _split_top_and_least_selling(rows)
        top_names = {row["name"] for row in top}
        least_names = {row["name"] for row in least}

        self.assertEqual(top_names, {"TROUSERS", "Samsung A56"})
        self.assertEqual(least_names, {"IPHONE PROMAX 17", "Redmi note 14 pro"})
        self.assertFalse(top_names & least_names)

    def test_no_overlap_when_more_than_three_products(self):
        rows = [
            {"name": "A", "total_qty": 10},
            {"name": "B", "total_qty": 9},
            {"name": "C", "total_qty": 8},
            {"name": "D", "total_qty": 2},
            {"name": "E", "total_qty": 1},
        ]
        top, least = _split_top_and_least_selling(rows)
        self.assertEqual([row["name"] for row in top], ["A", "B", "C"])
        self.assertEqual([row["name"] for row in least], ["E", "D"])
        top_names = {row["name"] for row in top}
        least_names = {row["name"] for row in least}
        self.assertFalse(top_names & least_names)


class MLRecommendationRuleTests(TestCase):
    def test_high_demand_low_risk_recommends_stock_increase(self):
        recommendation = _build_ml_recommendation(85, 40, 20, 80)
        self.assertEqual(
            recommendation,
            "Increase stock levels to meet growing customer demand.",
        )

    def test_low_demand_high_risk_recommends_inventory_reduction(self):
        recommendation = _build_ml_recommendation(20, 10, 85, 25)
        self.assertEqual(
            recommendation,
            "Reduce inventory to avoid overstocking.",
        )

    def test_high_demand_high_trend_recommends_marketing_focus(self):
        recommendation = _build_ml_recommendation(80, 85, 25, 75)
        self.assertEqual(
            recommendation,
            "Prioritize this item in marketing campaigns.",
        )


class AiItemSuggestionsTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Test Shop")
        self.user = User.objects.create_user(username="owner", password="pass12345")
        UserProfile.objects.filter(user=self.user).update(
            business=self.business,
            role=UserProfile.ROLE_EMPLOYER,
            is_business_active=True,
        )

        self.samsung = Item.objects.create(
            business=self.business,
            name="Samsung A56",
            unit_price=Decimal("100.00"),
            initial_quantity=10,
            current_quantity=10,
            stock_qty=10,
            created_by=self.user,
        )
        self.trousers = Item.objects.create(
            business=self.business,
            name="Trousers",
            unit_price=Decimal("50.00"),
            initial_quantity=10,
            current_quantity=10,
            stock_qty=10,
            created_by=self.user,
        )
        self.iphone = Item.objects.create(
            business=self.business,
            name="IPHONE PROMAX 17",
            unit_price=Decimal("500.00"),
            initial_quantity=10,
            current_quantity=10,
            stock_qty=10,
            created_by=self.user,
        )

    def _record_sale(self, item, quantity, sold_at):
        sale = Sale.objects.create(
            business=self.business,
            item=item,
            quantity=quantity,
            sold_by=self.user,
            payment_method=Sale.PAYMENT_CASH,
            total_amount=Decimal(quantity) * item.unit_price,
        )
        Sale.objects.filter(pk=sale.pk).update(sold_at=sold_at)
        sale.refresh_from_db()
        return sale

    def test_example_output_without_historical_growth_data(self):
        now = timezone.now()
        for _ in range(5):
            self._record_sale(self.samsung, 1, now)
        self._record_sale(self.trousers, 1, now)
        self._record_sale(self.iphone, 1, now)

        data = ai_item_suggestions(self.user)

        self.assertEqual([row["name"] for row in data["top_selling"]], ["Samsung A56"])
        self.assertEqual(
            [row["name"] for row in data["least_selling"]],
            ["IPHONE PROMAX 17", "Trousers"],
        )
        self.assertEqual(data["growth_items"], [])
        self.assertIn("Daily analysis", data["growth_message"])

    def test_ai_item_suggestions_return_actionable_recommendations(self):
        now = timezone.now()
        self._record_sale(self.samsung, 3, now)
        self._record_sale(self.trousers, 1, now)

        data = ai_item_suggestions(self.user)

        self.assertTrue(data["has_sales"])
        self.assertTrue(data["top_selling"][0]["recommendation"])
        self.assertIsInstance(data["least_selling"][0]["suggestions"], list)
        self.assertGreaterEqual(len(data["least_selling"][0]["suggestions"]), 1)

    def test_top_and_least_never_overlap(self):
        now = timezone.now()
        for qty, item in ((10, self.samsung), (9, self.trousers), (8, self.iphone)):
            for _ in range(qty):
                self._record_sale(item, 1, now)

        data = ai_item_suggestions(self.user)
        top_names = {row["name"] for row in data["top_selling"]}
        least_names = {row["name"] for row in data["least_selling"]}
        self.assertFalse(top_names & least_names)

    def test_growth_uses_period_over_period_not_new_product_spike(self):
        now = timezone.now()
        current_start = now - timedelta(days=3)
        previous_start = now - timedelta(days=10)

        self._record_sale(self.samsung, 2, previous_start)
        for _ in range(4):
            self._record_sale(self.samsung, 1, current_start)
        self._record_sale(self.trousers, 1, current_start)

        data = ai_item_suggestions(self.user)

        self.assertEqual(data["growth_items"], [])
        self.assertIn("Daily analysis", data["growth_message"])

    def test_unchanged_sales_show_zero_growth(self):
        now = timezone.now()
        period_time = now - timedelta(days=3)
        previous_time = now - timedelta(days=10)

        self._record_sale(self.samsung, 2, previous_time)
        self._record_sale(self.samsung, 2, period_time)

        data = ai_item_suggestions(self.user)
        self.assertEqual(data["growth_items"], [])
        self.assertIn("Daily analysis", data["growth_message"])
