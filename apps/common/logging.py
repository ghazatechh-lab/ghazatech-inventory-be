import logging
from collections.abc import Mapping

from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

logger = logging.getLogger("ghazatech.api")

SENSITIVE_KEYS = {
    "password",
    "old_password",
    "new_password",
    "confirm_password",
    "token",
    "access",
    "refresh",
    "authorization",
    "secret",
    "secret_key",
    "api_key",
}


def sanitize(value):
    """Return log-safe request data without passwords, tokens, or uploaded files."""
    if isinstance(value, Mapping):
        return {
            str(key): (
                "***REDACTED***"
                if str(key).lower() in SENSITIVE_KEYS
                else sanitize(item)
            )
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]

    if hasattr(value, "name") and hasattr(value, "size"):
        return {
            "file_name": getattr(value, "name", None),
            "file_size": getattr(value, "size", None),
            "content_type": getattr(value, "content_type", None),
        }

    return value


def request_context(request, view=None):
    user = getattr(request, "user", None)
    branch = getattr(user, "branch", None) if user and user.is_authenticated else None

    return {
        "method": request.method,
        "path": request.get_full_path(),
        "view": view.__class__.__name__ if view else None,
        "action": getattr(view, "action", None) if view else None,
        "user_id": (
            getattr(user, "id", None) if user and user.is_authenticated else None
        ),
        "branch_id": getattr(branch, "id", None),
        "query_params": sanitize(dict(request.query_params.lists())),
        "request_data": sanitize(request.data),
    }


class APILoggingMixin:
    """Structured request/response/error logging for DRF API views and viewsets."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        logger.info("API request started | %s", request_context(request, self))

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)

        context = request_context(request, self)
        context["status_code"] = response.status_code

        if response.status_code >= 400:
            context["response_data"] = sanitize(getattr(response, "data", None))
            logger.warning("API request failed | %s", context)
        else:
            logger.info("API request completed | %s", context)

        return response

    def handle_exception(self, exc):
        context = request_context(self.request, self)
        context["exception_type"] = exc.__class__.__name__
        context["exception_message"] = str(exc)

        if getattr(exc, "status_code", 500) >= 500:
            logger.exception("Unhandled API exception | %s", context)
        else:
            logger.warning("Handled API exception | %s", context)

        return super().handle_exception(exc)


class LoggedAPIView(APILoggingMixin, APIView):
    pass


class LoggedModelViewSet(APILoggingMixin, ModelViewSet):
    pass


class LoggedReadOnlyModelViewSet(APILoggingMixin, ReadOnlyModelViewSet):
    pass
