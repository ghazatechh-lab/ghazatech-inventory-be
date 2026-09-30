"""Secondary database settings for VAT and Non-VAT transactions."""

import os


def _postgres(name, host, user, password, port):
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": user,
        "PASSWORD": password,
        "HOST": host,
        "PORT": port,
    }


MULTI_DATABASES = {
    "vat": _postgres(
        os.getenv("VAT_POSTGRES_DB", "ghaza_vat_db"),
        os.getenv("VAT_POSTGRES_HOST", "db_vat"),
        os.getenv("VAT_POSTGRES_USER", "postgres"),
        os.getenv("VAT_POSTGRES_PASSWORD", "postgres"),
        os.getenv("VAT_POSTGRES_PORT", "5432"),
    ),
    "non_vat": _postgres(
        os.getenv("NON_VAT_POSTGRES_DB", "ghaza_non_vat_db"),
        os.getenv("NON_VAT_POSTGRES_HOST", "db_non_vat"),
        os.getenv("NON_VAT_POSTGRES_USER", "postgres"),
        os.getenv("NON_VAT_POSTGRES_PASSWORD", "postgres"),
        os.getenv("NON_VAT_POSTGRES_PORT", "5432"),
    ),
}

DATABASE_ROUTERS = ["apps.branch_data.router.BranchTransactionRouter"]
