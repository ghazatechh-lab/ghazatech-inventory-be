"""
Import from the active Django settings file after DATABASES is defined.

Required environment variables can follow your existing vat/non_vat setup.
This file intentionally does NOT define a third BR03 database.
"""

DATABASE_ROUTERS = [
    "apps.branch_data.router.GhazatechBranchRouter",
]

# Add after AuthenticationMiddleware / whichever middleware establishes user.
# MIDDLEWARE += [
#     "apps.branch_data.request_context.BranchDatabaseContextMiddleware",
# ]

# Required aliases:
# DATABASES["vat"] = {...}
# DATABASES["non_vat"] = {...}
#
# `default` remains for shared identity/configuration where applicable.
