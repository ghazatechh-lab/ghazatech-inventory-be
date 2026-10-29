"""Provision existing physical branch schema and minimum references; dry-run by default."""
from django.core.management.base import BaseCommand, CommandError
from apps.branches.models import Branch
from apps.branch_data.schema_routing import branch_alias
from apps.branch_data.provisioning import provision_physical_branch

class Command(BaseCommand):
    help = "Provision and initialize a physical branch (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument("branch_id", type=int)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        branch = Branch.objects.using("default").filter(pk=options["branch_id"]).first()
        if branch is None or branch.tax_mode not in {"VAT", "NON_VAT"}:
            raise CommandError("A VAT/NON_VAT physical branch is required")
        base, schema = branch_alias(branch.pk, branch.tax_mode)
        self.stdout.write(f"Branch {branch.pk}: {base}.{schema}")
        if not options["apply"]:
            self.stdout.write("DRY RUN: add --apply to migrate, initialize and register schema")
            return
        try:
            provision_physical_branch(branch.pk)
        except Exception as exc:
            raise CommandError(f"Provisioning failed; branch disabled: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Schema initialized: {base}.{schema}"))
        self.stdout.write("WARNING: full ERP schema routing and consolidated reporting still require integration")
