from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_multi_tenant_business"),
    ]

    operations = [
        migrations.AddField(
            model_name="business",
            name="amount_due",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=10, null=True
            ),
        ),
        migrations.AddField(
            model_name="business",
            name="due_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="business",
            name="notice_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="business",
            name="payment_notice",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="business",
            name="payment_status",
            field=models.CharField(
                choices=[
                    ("ok", "Paid / OK"),
                    ("due", "Payment due"),
                    ("overdue", "Payment overdue"),
                ],
                default="ok",
                max_length=20,
            ),
        ),
    ]
