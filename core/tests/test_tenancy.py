from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Business, Item, Sale, UserProfile


class TenantIsolationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.business_a = Business.objects.create(name="Tenant A")
        self.business_b = Business.objects.create(name="Tenant B")

        self.user_a = User.objects.create_user(username="user_a", password="pass12345")
        self.user_b = User.objects.create_user(username="user_b", password="pass12345")

        UserProfile.objects.filter(user=self.user_a).update(
            business=self.business_a,
            role=UserProfile.ROLE_EMPLOYER,
            is_business_active=True,
        )
        UserProfile.objects.filter(user=self.user_b).update(
            business=self.business_b,
            role=UserProfile.ROLE_EMPLOYER,
            is_business_active=True,
        )

        self.item_a = Item.objects.create(
            business=self.business_a,
            name="Product A",
            unit_price=Decimal("100.00"),
            initial_quantity=10,
            current_quantity=10,
            stock_qty=10,
            created_by=self.user_a,
        )
        Item.objects.create(
            business=self.business_b,
            name="Product B",
            unit_price=Decimal("50.00"),
            initial_quantity=5,
            current_quantity=5,
            stock_qty=5,
            created_by=self.user_b,
        )

    def test_scoped_querysets_hide_other_business_items(self):
        a_items = list(Item.objects.for_business(self.business_a).values_list("name", flat=True))
        b_items = list(Item.objects.for_business(self.business_b).values_list("name", flat=True))
        self.assertEqual(a_items, ["Product A"])
        self.assertEqual(b_items, ["Product B"])

    def test_user_cannot_fetch_other_business_item_by_pk(self):
        other_item = Item.objects.for_business(self.business_b).get()
        self.client.login(username="user_a", password="pass12345")
        session = self.client.session
        session["active_role"] = UserProfile.ROLE_EMPLOYER
        session.save()

        response = self.client.post(
            reverse("employer-dashboard"),
            {
                "action": "cancel_item",
                "item_id": other_item.pk,
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_sales_are_scoped_per_business(self):
        Sale.objects.create(
            business=self.business_a,
            item=self.item_a,
            quantity=1,
            sold_by=self.user_a,
            payment_method=Sale.PAYMENT_CASH,
            total_amount=Decimal("100.00"),
        )
        self.assertEqual(Sale.objects.for_business(self.business_a).count(), 1)
        self.assertEqual(Sale.objects.for_business(self.business_b).count(), 0)
