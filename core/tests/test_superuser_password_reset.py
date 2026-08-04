from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Business, UserProfile


class SuperuserPasswordResetTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="adminpass123",
        )
        self.business = Business.objects.create(name="Reset Test Co")
        self.employer = User.objects.create_user(
            username="biz_employer",
            password="oldlogin123",
        )
        self.profile = UserProfile.objects.get(user=self.employer)
        self.profile.business = self.business
        self.profile.role = UserProfile.ROLE_EMPLOYER
        self.profile.is_business_active = True
        self.profile.set_employer_password("oldemployer123")
        self.profile.save()

    def _login_superuser(self):
        self.client.login(username="admin", password="adminpass123")

    def test_superuser_can_reset_business_login_password(self):
        self._login_superuser()
        response = self.client.post(
            reverse("superuser-dashboard"),
            {
                "action": "reset_password",
                "profile_id": self.profile.pk,
                "login_password": "newlogin123",
                "login_password_confirm": "newlogin123",
            },
        )
        self.assertEqual(response.status_code, 302)

        self.employer.refresh_from_db()
        self.assertTrue(self.employer.check_password("newlogin123"))
        self.assertFalse(self.employer.check_password("oldlogin123"))

    def test_superuser_can_reset_employer_password(self):
        self._login_superuser()
        response = self.client.post(
            reverse("superuser-dashboard"),
            {
                "action": "reset_password",
                "profile_id": self.profile.pk,
                "employer_password": "newemployer123",
                "employer_password_confirm": "newemployer123",
            },
        )
        self.assertEqual(response.status_code, 302)

        self.profile.refresh_from_db()
        self.assertTrue(self.profile.check_employer_password("newemployer123"))
        self.assertFalse(self.profile.check_employer_password("oldemployer123"))

    def test_employer_can_change_their_login_password(self):
        self.client.login(username="biz_employer", password="oldlogin123")
        session = self.client.session
        session["active_role"] = UserProfile.ROLE_EMPLOYER
        session.save()

        response = self.client.post(
            reverse("employer-dashboard"),
            {
                "action": "change_password",
                "old_password": "oldlogin123",
                "new_login_password1": "NewLogin456!",
                "new_login_password2": "NewLogin456!",
            },
        )
        self.assertEqual(response.status_code, 302)

        self.employer.refresh_from_db()
        self.assertTrue(self.employer.check_password("NewLogin456!"))
        self.assertFalse(self.employer.check_password("oldlogin123"))

    def test_employer_can_change_their_employer_password(self):
        self.client.login(username="biz_employer", password="oldlogin123")
        session = self.client.session
        session["active_role"] = UserProfile.ROLE_EMPLOYER
        session.save()

        response = self.client.post(
            reverse("employer-dashboard"),
            {
                "action": "change_password",
                "old_password": "oldlogin123",
                "new_employer_password1": "EmployerNew456!",
                "new_employer_password2": "EmployerNew456!",
            },
        )
        self.assertEqual(response.status_code, 302)

        self.profile.refresh_from_db()
        self.assertTrue(self.profile.check_employer_password("EmployerNew456!"))
        self.assertFalse(self.profile.check_employer_password("oldemployer123"))

    def test_non_superuser_cannot_reset_passwords(self):
        self.client.login(username="biz_employer", password="oldlogin123")
        response = self.client.post(
            reverse("superuser-dashboard"),
            {
                "action": "reset_password",
                "profile_id": self.profile.pk,
                "login_password": "hackedlogin123",
                "login_password_confirm": "hackedlogin123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.url, reverse("superuser-dashboard"))

        self.employer.refresh_from_db()
        self.assertTrue(self.employer.check_password("oldlogin123"))
