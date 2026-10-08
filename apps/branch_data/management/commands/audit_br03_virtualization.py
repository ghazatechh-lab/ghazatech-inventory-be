from django.apps import apps
from django.core.management.base import BaseCommand

from apps.branches.models import Branch


APP_LABELS = [
    "inventory",
    "purchases",
    "sales",
    "suppliers",
    "customers",
    "finance",
    "shipments",
    "transfers",
]


class Command(BaseCommand):
    help = (
        "Audit records currently owned by BR03 before converting BR03 into "
        "a virtual combined branch. This command never changes data."
    )

    def handle(self, *args, **options):
        branch = Branch.objects.filter(branch_code="BR03").first()
        if not branch:
            self.stdout.write(self.style.WARNING("BR03 was not found."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"BR03 audit: id={branch.id} name={branch.branch_name}"
            )
        )

        total = 0

        for app_label in APP_LABELS:
            try:
                config = apps.get_app_config(app_label)
            except LookupError:
                continue

            for model in config.get_models():
                field_names = {field.name for field in model._meta.fields}
                if "branch" not in field_names:
                    continue

                try:
                    count = model._default_manager.filter(branch=branch).count()
                except Exception as exc:
                    self.stdout.write(
                        self.style.WARNING(
                            f"{app_label}.{model.__name__}: unable to count ({exc})"
                        )
                    )
                    continue

                if count:
                    total += count
                    self.stdout.write(
                        f"{app_label}.{model.__name__}: {count}"
                    )

        self.stdout.write("")
        self.stdout.write(f"Total BR03-owned records: {total}")

        if total:
            self.stdout.write(
                self.style.WARNING(
                    "Do NOT delete BR03 transactional records. Classify every "
                    "record as VAT or NON_VAT and migrate it before enabling "
                    "virtual-only enforcement."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "No BR03-owned transactional rows detected in the default DB."
                )
            )
