"""Opt-in supplier-only tenant routing, isolated to one HTTP request."""
from contextlib import contextmanager
from contextvars import ContextVar

_supplier_tenant_scope = ContextVar("ghaza_supplier_tenant_scope", default=False)


def supplier_tenant_scope_active():
    return _supplier_tenant_scope.get()


@contextmanager
def supplier_tenant_scope():
    token = _supplier_tenant_scope.set(True)
    try:
        yield
    finally:
        _supplier_tenant_scope.reset(token)
