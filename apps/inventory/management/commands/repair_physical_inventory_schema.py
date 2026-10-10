from django.core.management.base import BaseCommand, CommandError
from django.db import connections, router
from django.db.migrations.loader import MigrationLoader


class Command(BaseCommand):
    help = "Create missing physical inventory tables from migration state; dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument("--database", required=True, choices=("vat", "non_vat"))
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        alias = options["database"]
        if alias not in connections:
            raise CommandError(f"Database alias {alias} is not configured.")
        connection = connections[alias]
        if connection.vendor != "postgresql":
            raise CommandError("This repair supports PostgreSQL only.")
        loader = MigrationLoader(connection)
        loader.check_consistent_history(connection)
        leaves = loader.graph.leaf_nodes("inventory")
        if not leaves or any(node not in loader.applied_migrations for node in leaves):
            raise CommandError("Apply pending inventory migrations first; no tables changed.")
        state = loader.project_state()
        models = list(state.apps.get_app_config("inventory").get_models(include_auto_created=True))
        models = [model for model in models if model._meta.managed and not model._meta.proxy]
        tables = set(connection.introspection.table_names())
        missing = [model for model in models if model._meta.db_table not in tables]
        for model in missing:
            if not router.allow_migrate(alias, "inventory", model_name=model._meta.model_name):
                raise CommandError(f"Router does not allow {model._meta.db_table} in {alias}.")
        if not missing:
            self.stdout.write(self.style.SUCCESS(f"{alias}: all inventory tables exist; no changes."))
            return

        # Refuse before DDL if required external schemas are missing.
        planned_tables = {model._meta.db_table for model in missing}
        missing_dependencies = set()
        for model in missing:
            for field in model._meta.local_fields:
                if field.is_relation and field.remote_field:
                    target = field.remote_field.model._meta.db_table
                    if target not in tables | planned_tables:
                        missing_dependencies.add(target)
        if missing_dependencies:
            raise CommandError("Required reference tables are absent: " + ", ".join(sorted(missing_dependencies)))

        # create_model recursively creates auto M2M tables. Do not recreate
        # a through table already present or schedule it a second time.
        automatic = set()
        for model in missing:
            if model._meta.auto_created:
                continue
            for field in model._meta.local_many_to_many:
                through = field.remote_field.through
                if through._meta.auto_created:
                    if through._meta.db_table in tables:
                        raise CommandError(f"Unexpected existing through table {through._meta.db_table}; manual review required.")
                    automatic.add(through._meta.db_table)
        pending = [model for model in missing if model._meta.db_table not in automatic]
        ordered = []
        # Referenced missing models first; self-FKs do not create an ordering edge.
        while pending:
            pending_tables = {model._meta.db_table for model in pending}
            ready = []
            for model in pending:
                dependencies = {
                    field.remote_field.model._meta.db_table
                    for field in model._meta.local_fields
                    if field.is_relation and field.remote_field
                } - {model._meta.db_table}
                if not dependencies & pending_tables:
                    ready.append(model)
            if not ready:
                raise CommandError("Cyclic missing-table dependencies; manual review required.")
            ordered.extend(ready)
            pending = [model for model in pending if model not in ready]

        self.stdout.write(f"{alias}: missing inventory tables:")
        for model in missing:
            self.stdout.write(f"  {model._meta.db_table}")
        if not options["apply"]:
            self.stdout.write("Dry run only. Rerun with --apply after taking a database backup.")
            return
        # PostgreSQL transactional DDL includes the deferred FK/index statements.
        # Existing tables/data and django_migrations are never altered here.
        with connection.schema_editor(atomic=True) as editor:
            for model in ordered:
                editor.create_model(model)
        remaining = planned_tables - set(connection.introspection.table_names())
        if remaining:
            raise CommandError("Tables still absent: " + ", ".join(sorted(remaining)))
        self.stdout.write(self.style.SUCCESS(f"{alias}: missing inventory tables created. Existing data preserved."))
