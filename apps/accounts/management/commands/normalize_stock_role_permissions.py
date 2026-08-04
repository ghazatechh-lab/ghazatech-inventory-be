import json

from django.core.management.base import BaseCommand

from apps.accounts.models import Role

ALIASES = {
    "sales.selling.non_restricted": "sales.selling.regular",
    "purchases.stock_purchase.non_restricted": "purchases.stock_purchase.regular",
}

OBSOLETE_PREFIXES = ("inventory.non_restricted_stock.",)


def normalize_permission_value(value):
    """
    Convert supported role permission formats into a clean list.

    Supported formats:
    - ["sales.selling.regular"]
    - [{"code": "sales.selling.regular"}]
    - '{"sales.selling.regular": true}'
    - {"sales": {"selling": {"regular": true}}}
    - "sales.selling.regular,sales.selling.vat"
    """
    if value is None or value == "":
        return []

    if isinstance(value, (list, tuple, set)):
        result = []

        for item in value:
            if isinstance(item, str):
                code = item.strip()

                if code:
                    result.append(code)

            elif isinstance(item, dict):
                code = (
                    item.get("code")
                    or item.get("permission_code")
                    or item.get("permission")
                    or item.get("name")
                )

                if isinstance(code, str) and code.strip():
                    result.append(code.strip())

        return result

    if isinstance(value, str):
        stripped = value.strip()

        if not stripped:
            return []

        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError, json.JSONDecodeError):
            return [item.strip() for item in stripped.split(",") if item.strip()]

        return normalize_permission_value(parsed)

    if isinstance(value, dict):
        if "permissions" in value:
            return normalize_permission_value(value["permissions"])

        if "results" in value:
            return normalize_permission_value(value["results"])

        if "data" in value:
            return normalize_permission_value(value["data"])

        result = []

        def visit(node, path=None):
            path = path or []

            if node is True:
                if path:
                    result.append(".".join(path))
                return

            if node in (False, None):
                return

            if isinstance(node, dict):
                for key, child in node.items():
                    visit(child, [*path, str(key)])

            elif isinstance(node, list):
                for child in node:
                    if isinstance(child, str):
                        if child.strip():
                            result.append(child.strip())

                    elif isinstance(child, dict):
                        code = (
                            child.get("code")
                            or child.get("permission_code")
                            or child.get("permission")
                            or child.get("name")
                        )

                        if isinstance(code, str) and code.strip():
                            result.append(code.strip())

        visit(value)

        return result

    return []


def normalize_permission_codes(value):
    normalized = []

    for permission in normalize_permission_value(value):
        code = str(permission or "").strip()

        if not code:
            continue

        if code.startswith(OBSOLETE_PREFIXES):
            continue

        code = ALIASES.get(code, code)

        if code not in normalized:
            normalized.append(code)

    return normalized


class Command(BaseCommand):
    help = (
        "Normalize role permissions to use only "
        "REGULAR and RESTRICTED stock classifications."
    )

    def handle(self, *args, **options):
        updated = 0
        unchanged = 0
        failed = 0

        for role in Role.objects.all().order_by("id"):
            try:
                current_raw = role.permissions
                normalized = normalize_permission_codes(current_raw)

                # Compare against a normalized form of the current value
                # so JSON strings/dicts are converted and saved as list[].
                current_normalized = normalize_permission_codes(current_raw)

                needs_update = (
                    not isinstance(current_raw, list)
                    or normalized != current_normalized
                    or current_raw != normalized
                )

                if needs_update:
                    role.permissions = normalized
                    role.save(update_fields=["permissions"])
                    updated += 1

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Updated {role.code}: " f"{len(normalized)} permissions"
                        )
                    )
                else:
                    unchanged += 1

                    self.stdout.write(f"Unchanged {role.code}")

            except Exception as exc:
                failed += 1

                self.stderr.write(self.style.ERROR(f"Failed {role.code}: {exc}"))

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Completed. Updated: {updated}, "
                f"Unchanged: {unchanged}, Failed: {failed}"
            )
        )
