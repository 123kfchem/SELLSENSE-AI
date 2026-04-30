from django.db import migrations, models


def populate_quantities_from_stock(apps, schema_editor):
    Item = apps.get_model("core", "Item")
    for item in Item.objects.all():
        item.initial_quantity = item.stock_qty
        item.current_quantity = item.stock_qty
        item.save(update_fields=["initial_quantity", "current_quantity"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_userprofile_business_name_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="current_quantity",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="item",
            name="initial_quantity",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="employer_password_hash",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.RunPython(populate_quantities_from_stock, migrations.RunPython.noop),
    ]
