from contextvars import ContextVar

_active_branch_id = ContextVar("active_branch_id", default=None)


def set_active_branch_id(value):
    try:
        value = int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        value = None
    return _active_branch_id.set(value)


def reset_active_branch_id(token):
    _active_branch_id.reset(token)


def get_active_branch_id():
    return _active_branch_id.get()
