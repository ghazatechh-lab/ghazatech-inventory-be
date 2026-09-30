from django.apps import apps
from django.core.management.base import BaseCommand

MODEL_ORDER = [
    ("branches", "Branch"),
    ("accounts", "Role"),
    ("accounts", "User"),
    ("inventory", "Brand"),
    ("inventory", "Category"),
    ("inventory", "Rack"),
    ("inventory", "Product"),
    ("inventory", "ProductVariant"),
]


def copy_model(model, target):
    fields = [
        field
        for field in model._meta.concrete_fields
        if not field.auto_created and not (field.primary_key and field.auto_created)
    ]

    copied = 0

    for obj in model.objects.using("default").all().iterator():
        values = {}

        for field in fields:
            if field.primary_key:
                continue

            if field.is_relation:
                related_model = getattr(field, "related_model", None)
                related_app = (
                    related_model._meta.app_label if related_model is not None else None
                )

                # HRMS is MASTER-only business data. accounts.User may have an
                # optional FK to hrms.Employee, but secondary DBs contain only
                # the HRMS schema needed for the FK constraint.
                if related_app == "hrms":
                    if field.null:
                        values[field.attname] = None
                        continue

                    raise RuntimeError(
                        f"Cannot mirror {model._meta.label}.{field.name}: "
                        "non-null HRMS relation cannot be copied to a "
                        "transaction database."
                    )

                values[field.attname] = getattr(obj, field.attname)
            else:
                values[field.name] = getattr(obj, field.name)

        model.objects.using(target).update_or_create(
            pk=obj.pk,
            defaults=values,
        )
        copied += 1

    return copied


class Command(BaseCommand):
    help = "Mirror shared reference rows to VAT and Non-VAT databases."

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            choices=["vat", "non_vat", "all"],
            default="all",
        )

    def handle(self, *args, **options):
        targets = (
            ["vat", "non_vat"]
            if options["database"] == "all"
            else [options["database"]]
        )

        for target in targets:
            self.stdout.write(f"Syncing references to {target}...")

            for app_label, model_name in MODEL_ORDER:
                try:
                    model = apps.get_model(app_label, model_name)
                except LookupError:
                    continue

                count = copy_model(model, target)

                self.stdout.write(f"  {app_label}.{model_name}: {count}")
