import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def migrate_tenant_data(apps, schema_editor):
    Business = apps.get_model("core", "Business")
    UserProfile = apps.get_model("core", "UserProfile")
    Item = apps.get_model("core", "Item")
    Sale = apps.get_model("core", "Sale")
    ItemReport = apps.get_model("core", "ItemReport")

    business_by_name = {}

    def get_or_create_business(name, phone="", location="", is_active=True):
        key = (name or "").strip() or "Unassigned Business"
        if key not in business_by_name:
            business_by_name[key] = Business.objects.create(
                name=key,
                phone_number=phone or "",
                location=location or "",
                is_active=is_active,
            )
        return business_by_name[key]

    for profile in UserProfile.objects.select_related("user").all():
        name = (profile.business_name or "").strip() or f"Business {profile.user.username}"
        business = get_or_create_business(
            name,
            phone=profile.phone_number,
            location=profile.location,
            is_active=profile.is_business_active,
        )
        profile.business = business
        profile.save(update_fields=["business"])

    legacy = Business.objects.filter(name="Legacy Unassigned").first()
    if not business_by_name and not legacy:
        legacy = Business.objects.create(name="Legacy Unassigned")
    fallback_business = legacy or next(iter(business_by_name.values()), None)

    user_business = {
        profile.user_id: profile.business_id
        for profile in UserProfile.objects.exclude(business_id__isnull=True)
    }

    for item in Item.objects.all():
        business_id = None
        if item.created_by_id and item.created_by_id in user_business:
            business_id = user_business[item.created_by_id]
        if not business_id and fallback_business:
            business_id = fallback_business.id
        item.business_id = business_id
        item.save(update_fields=["business"])

    for sale in Sale.objects.select_related("item").all():
        if sale.item_id and sale.item.business_id:
            sale.business_id = sale.item.business_id
        elif sale.sold_by_id and sale.sold_by_id in user_business:
            sale.business_id = user_business[sale.sold_by_id]
        elif fallback_business:
            sale.business_id = fallback_business.id
        sale.save(update_fields=["business"])

    for report in ItemReport.objects.select_related("item").all():
        if report.item_id and report.item.business_id:
            report.business_id = report.item.business_id
        elif report.reported_by_id and report.reported_by_id in user_business:
            report.business_id = user_business[report.reported_by_id]
        elif fallback_business:
            report.business_id = fallback_business.id
        report.save(update_fields=["business"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_item_initial_quantity_item_current_quantity_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Business",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=180)),
                ("phone_number", models.CharField(blank=True, max_length=30)),
                ("location", models.CharField(blank=True, max_length=180)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["name"],
                "verbose_name_plural": "businesses",
            },
        ),
        migrations.AddField(
            model_name="userprofile",
            name="business",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="members",
                to="core.business",
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="business",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="items",
                to="core.business",
            ),
        ),
        migrations.AddField(
            model_name="sale",
            name="business",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sales",
                to="core.business",
            ),
        ),
        migrations.AddField(
            model_name="itemreport",
            name="business",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="itemreports",
                to="core.business",
            ),
        ),
        migrations.RunPython(migrate_tenant_data, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="userprofile",
            name="business_name",
        ),
        migrations.RemoveField(
            model_name="userprofile",
            name="location",
        ),
        migrations.RemoveField(
            model_name="userprofile",
            name="phone_number",
        ),
        migrations.AlterField(
            model_name="item",
            name="business",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="items",
                to="core.business",
            ),
        ),
        migrations.AlterField(
            model_name="sale",
            name="business",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sales",
                to="core.business",
            ),
        ),
        migrations.AlterField(
            model_name="itemreport",
            name="business",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="itemreports",
                to="core.business",
            ),
        ),
        migrations.AddConstraint(
            model_name="item",
            constraint=models.UniqueConstraint(fields=("business", "name"), name="uniq_item_name_per_business"),
        ),
        migrations.AddIndex(
            model_name="sale",
            index=models.Index(fields=["business", "sold_at"], name="core_sale_busines_0b0e0d_idx"),
        ),
    ]
