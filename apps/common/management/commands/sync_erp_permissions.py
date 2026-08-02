from django.apps import apps
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from apps.common.permission_catalog import (
    iter_permission_codes,
)


class Command(BaseCommand):
    help = "Create/update all Ghazatech ERP permissions."

    def handle(self, *args, **options):
        created = 0
        updated = 0
        skipped = []

        installed_labels = {config.label: config for config in apps.get_app_configs()}

        for code in iter_permission_codes():
            app_label, codename = code.split(
                ".",
                1,
            )

            app_config = installed_labels.get(app_label)

            if not app_config:
                skipped.append(code)
                continue

            model = next(
                iter(app_config.get_models()),
                None,
            )

            if not model:
                skipped.append(code)
                continue

            content_type = ContentType.objects.get_for_model(model)

            permission, was_created = Permission.objects.update_or_create(
                content_type=content_type,
                codename=codename,
                defaults={
                    "name": code.replace(
                        ".",
                        " ",
                    )
                    .replace(
                        "_",
                        " ",
                    )
                    .title(),
                },
            )

            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(f"Created {created}, updated {updated} permissions.")
        )

        if skipped:
            self.stdout.write(
                self.style.WARNING(
                    "Skipped permissions for unavailable apps: " + ", ".join(skipped)
                )
            )
