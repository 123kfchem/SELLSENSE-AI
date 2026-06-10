from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Business, UserProfile


class PaymentNoticeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username="admin",
            password="adminpass123",
            email="admin@example.com",
        )
        self.business = Business.objects.create(name="Test Shop")
        self.user = User.objects.create_user(username="shop_owner", password="pass12345")
        UserProfile.objects.filter(user=self.user).update(
            business=self.business,
            role=UserProfile.ROLE_EMPLOYER,
            is_business_active=True,
        )

    def test_superuser_can_send_payment_notice(self):
        self.client.login(username="admin", password="adminpass123")
        profile = self.user.profile
        due_date = (timezone.localdate() + timedelta(days=7)).isoformat()
        response = self.client.post(
            reverse("superuser-dashboard"),
            {
                "action": "send_payment_notice",
                "profile_id": profile.id,
                "amount_due": "2500.00",
                "due_date": due_date,
                "payment_notice": "Pay via M-Pesa Paybill 123456.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.business.refresh_from_db()
        self.assertEqual(self.business.payment_status, Business.PAYMENT_DUE)
        self.assertEqual(self.business.amount_due, Decimal("2500.00"))
        self.assertEqual(self.business.payment_notice, "Pay via M-Pesa Paybill 123456.")

    def test_business_user_sees_payment_banner(self):
        self.business.payment_status = Business.PAYMENT_DUE
        self.business.amount_due = Decimal("1000.00")
        self.business.due_date = timezone.localdate() + timedelta(days=3)
        self.business.payment_notice = "Please pay to continue."
        self.business.save()

        self.client.login(username="shop_owner", password="pass12345")
        response = self.client.get(reverse("role-select"))
        self.assertContains(response, "Payment required to continue using SellSense AI")
        self.assertContains(response, "KES 1000.00")
        self.assertContains(response, "Please pay to continue.")

    def test_overdue_payment_blocks_login(self):
        self.business.payment_status = Business.PAYMENT_OVERDUE
        self.business.amount_due = Decimal("1000.00")
        self.business.due_date = timezone.localdate() - timedelta(days=1)
        self.business.payment_notice = "Overdue."
        self.business.save()

        response = self.client.post(
            reverse("login"),
            {"username": "shop_owner", "password": "pass12345"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "subscription payment is overdue")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_superuser_can_clear_payment_notice(self):
        self.business.payment_status = Business.PAYMENT_DUE
        self.business.amount_due = Decimal("500.00")
        self.business.due_date = timezone.localdate() + timedelta(days=2)
        self.business.payment_notice = "Pay now."
        self.business.save()

        self.client.login(username="admin", password="adminpass123")
        response = self.client.post(
            reverse("superuser-dashboard"),
            {
                "action": "clear_payment_notice",
                "profile_id": self.user.profile.id,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.business.refresh_from_db()
        self.assertEqual(self.business.payment_status, Business.PAYMENT_OK)
        self.assertIsNone(self.business.amount_due)
