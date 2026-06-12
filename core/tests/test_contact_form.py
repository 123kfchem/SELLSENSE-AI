from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse


class ContactFormTests(TestCase):
    def setUp(self):
        self.client = Client()

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        CONTACT_EMAIL="support@example.com",
        DEFAULT_FROM_EMAIL="noreply@example.com",
    )
    def test_contact_form_submits_and_sends_email(self):
        response = self.client.post(
            reverse("home"),
            {
                "form_type": "contact",
                "full_name": "Jane Doe",
                "phone_number": "+254 700 000 000",
                "email": "jane@example.com",
                "company_name": "Example Co",
                "subject": "Question about SellSense AI",
                "message": "Hello, I would like to learn more about your product.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("home")))
        self.assertIn("?contact_sent=1#contact", response.url)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.subject, "SellSense AI Contact: Question about SellSense AI")
        self.assertEqual(email.to, ["support@example.com"])
        self.assertEqual(email.from_email, "noreply@example.com")
        self.assertIn("Jane Doe", email.body)
        self.assertIn("jane@example.com", email.body)
        self.assertIn("Hello, I would like to learn more about your product.", email.body)
