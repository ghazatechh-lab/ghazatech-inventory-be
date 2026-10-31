"""Add optional catalog image columns to the current public + tenant schemas."""
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

class Command(BaseCommand):
    help = "Inspect/sync Brand and Category image columns in every existing PostgreSQL tenant schema."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        for alias in ("default", "vat", "non_vat"):
            connection = connections[alias]
            if connection.vendor != "postgresql":
                raise CommandError(f"{alias}: PostgreSQL required")
            with connection.cursor() as cursor:
                cursor.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name='public' OR schema_name ~ '^branch_[0-9]+$' ORDER BY schema_name")
                schemas = [row[0] for row in cursor.fetchall()]
                for schema in schemas:
                    for table in ("inventory_brand", "inventory_category"):
                        cursor.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s)", [schema, table])
                        if not cursor.fetchone()[0]:
                            continue
                        cursor.execute("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND column_name='image')", [schema, table])
                        if cursor.fetchone()[0]:
                            self.stdout.write(f"{alias}.{schema}.{table}: OK")
                            continue
                        self.stdout.write(f"{alias}.{schema}.{table}: MISSING image column")
                        if options["apply"]:
                            quoted_schema = connection.ops.quote_name(schema)
                            quoted_table = connection.ops.quote_name(table)
                            with connection.cursor() as ddl:
                                ddl.execute(f"ALTER TABLE {quoted_schema}.{quoted_table} ADD COLUMN IF NOT EXISTS image varchar(100) NULL")
                            self.stdout.write(self.style.SUCCESS("  Added image column"))
        if not options["apply"]:
            self.stdout.write("DRY RUN. Add --apply to update existing schemas.")
