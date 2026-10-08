from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connections

from apps.branches.models import Branch


PHYSICAL_DATABASES = {
    "vat": "BR01",
    "non_vat": "BR02",
}


class Command(BaseCommand):
    help = (
        "Audit physical databases for branch ownership and branch-aware foreign-key "
        "mismatches that can indicate cross-database ID reuse."
    )

    def handle(self, *args, **options):
        branches = {
            branch.branch_code.upper(): branch
            for branch in Branch.objects.using("default").filter(
                branch_code__in=["BR01", "BR02"]
            )
        }
        total_issues = 0

        for alias, branch_code in PHYSICAL_DATABASES.items():
            branch = branches.get(branch_code)
            if not branch:
                self.stdout.write(self.style.ERROR(f"{branch_code} is missing."))
                total_issues += 1
                continue

            self.stdout.write(f"\n[{alias}] expected branch: {branch_code} (id={branch.id})")
            connection = connections[alias]
            existing_tables = set(connection.introspection.table_names())

            for model in apps.get_models():
                if model._meta.proxy or not model._meta.managed:
                    continue
                if model._meta.db_table not in existing_tables:
                    continue

                field_names = {field.name for field in model._meta.fields}
                if "branch" not in field_names:
                    continue

                manager = model._default_manager.using(alias)
                wrong_owner_count = manager.exclude(branch_id=branch.id).exclude(
                    branch_id__isnull=True
                ).count()
                if wrong_owner_count:
                    total_issues += wrong_owner_count
                    self.stdout.write(
                        self.style.ERROR(
                            f"  {model._meta.label}: {wrong_owner_count} row(s) owned by "
                            f"a branch other than {branch_code}."
                        )
                    )

                for field in model._meta.fields:
                    if not field.is_relation or not field.many_to_one:
                        continue
                    if field.name == "branch" or field.remote_field is None:
                        continue
                    related_model = field.remote_field.model
                    related_fields = {f.name for f in related_model._meta.fields}
                    if "branch" not in related_fields:
                        continue
                    if related_model._meta.db_table not in existing_tables:
                        continue

                    # Compare branch IDs in SQL so no relation is accidentally
                    # resolved through another database router.
                    table = connection.ops.quote_name(model._meta.db_table)
                    related_table = connection.ops.quote_name(
                        related_model._meta.db_table
                    )
                    fk_column = connection.ops.quote_name(field.column)
                    pk_column = connection.ops.quote_name(
                        related_model._meta.pk.column
                    )
                    branch_column = connection.ops.quote_name(
                        model._meta.get_field("branch").column
                    )
                    related_branch_column = connection.ops.quote_name(
                        related_model._meta.get_field("branch").column
                    )

                    sql = f"""
                        SELECT COUNT(*)
                        FROM {table} src
                        JOIN {related_table} rel
                          ON src.{fk_column} = rel.{pk_column}
                        WHERE src.{fk_column} IS NOT NULL
                          AND src.{branch_column} IS NOT NULL
                          AND rel.{related_branch_column} IS NOT NULL
                          AND src.{branch_column} <> rel.{related_branch_column}
                    """
                    with connection.cursor() as cursor:
                        cursor.execute(sql)
                        mismatch_count = int(cursor.fetchone()[0] or 0)
                    if mismatch_count:
                        total_issues += mismatch_count
                        self.stdout.write(
                            self.style.ERROR(
                                f"  {model._meta.label}.{field.name}: "
                                f"{mismatch_count} wrong-branch relation(s)."
                            )
                        )

        if total_issues:
            self.stdout.write(
                self.style.ERROR(
                    f"\nCross-database FK audit found {total_issues} issue(s)."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nCross-database FK audit passed: no wrong-branch relations found."
                )
            )
