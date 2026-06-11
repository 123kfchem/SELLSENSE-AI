from django.db import migrations, models
from django.db.models import Min
from django.utils import timezone


def backfill_year_start_from_first_sale(apps, schema_editor):
    Business = apps.get_model("core", "Business")
    Sale = apps.get_model("core", "Sale")
    for business in Business.objects.all():
        first_sale = (
            Sale.objects.filter(business_id=business.pk)
            .aggregate(first_sold_at=Min("sold_at"))
            .get("first_sold_at")
        )
        if first_sale is None:
            continue
        local_date = timezone.localtime(first_sale).date()
        business.year_start_date = local_date
        business.save(update_fields=["year_start_date"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_expense"),
    ]

    operations = [
        migrations.AddField(
            model_name="business",
            name="year_start_date",
            field=models.DateField(
                blank=True,
                help_text="Date of the first recorded sale; anchors the business year for yearly reports.",
                null=True,
            ),
        ),
        migrations.RunPython(
            backfill_year_start_from_first_sale,
            migrations.RunPython.noop,
        ),
    ]
