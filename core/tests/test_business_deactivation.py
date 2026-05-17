from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Business, UserProfile


class BusinessDeactivationLoginTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.active_business = Business.objects.create(name="Active Co", is_active=True)
        self.inactive_business = Business.objects.create(name="Inactive Co", is_active=False)

        self.active_user = User.objects.create_user(
            username="active_user",
            password="pass12345",
        )
        self.inactive_user = User.objects.create_user(
            username="inactive_user",
            password="pass12345",
        )

        UserProfile.objects.filter(user=self.active_user).update(
            business=self.active_business,
            role=UserProfile.ROLE_EMPLOYER,
            is_business_active=True,
        )
        UserProfile.objects.filter(user=self.inactive_user).update(
            business=self.inactive_business,
            role=UserProfile.ROLE_EMPLOYER,
            is_business_active=False,
        )

    def test_deactivated_business_cannot_log_in(self):
        response = self.client.post(
            reverse("login"),
            {"username": "inactive_user", "password": "pass12345"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Your business account has been deactivated. Contact admin.",
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_active_business_can_log_in(self):
        response = self.client.post(
            reverse("login"),
            {"username": "active_user", "password": "pass12345"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("_auth_user_id", self.client.session)

    def test_deactivating_business_blocks_only_that_tenant(self):
        other_active = User.objects.create_user(
            username="other_active",
            password="pass12345",
        )
        UserProfile.objects.filter(user=other_active).update(
            business=self.active_business,
            role=UserProfile.ROLE_EMPLOYEE,
            is_business_active=True,
        )

        self.inactive_business.is_active = False
        self.inactive_business.save()

        blocked_client = Client()
        blocked = blocked_client.post(
            reverse("login"),
            {"username": "inactive_user", "password": "pass12345"},
        )
        self.assertContains(
            blocked,
            "Your business account has been deactivated. Contact admin.",
        )

        allowed_client = Client()
        allowed = allowed_client.post(
            reverse("login"),
            {"username": "other_active", "password": "pass12345"},
        )
        self.assertEqual(allowed.status_code, 302)
        self.assertIn("_auth_user_id", allowed_client.session)
