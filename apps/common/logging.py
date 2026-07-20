import logging
from collections.abc import Mapping

from django.core.files.uploadedfile import UploadedFile
from django.http import QueryDict
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


def _file_metadata(value):
    return {
        "file_name": getattr(value, "name", None),
        "file_size": getattr(value, "size", None),
        "content_type": getattr(value, "content_type", None),
    }


def sanitize(value):
    """Return JSON/log-safe data without secrets or raw uploaded-file bytes."""
    if isinstance(value, UploadedFile) or (
        hasattr(value, "name") and hasattr(value, "size") and hasattr(value, "read")
    ):
        return _file_metadata(value)

    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"binary_data": True, "size": len(value)}

    if isinstance(value, QueryDict):
        cleaned = {}
        for key in value.keys():
            values = value.getlist(key)
            safe_values = [
                (
                    "***REDACTED***"
                    if str(key).lower() in SENSITIVE_KEYS
                    else sanitize(item)
                )
                for item in values
            ]
            cleaned[str(key)] = safe_values[0] if len(safe_values) == 1 else safe_values
        return cleaned

    if isinstance(value, Mapping):
        return {
            str(key): (
                "***REDACTED***"
                if str(key).lower() in SENSITIVE_KEYS
                else sanitize(item)
            )
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [sanitize(item) for item in value]

    try:
        return str(value) if value.__class__.__name__ == "ErrorDetail" else value
    except (UnicodeDecodeError, UnicodeEncodeError):
        return "<unreadable binary value>"


def safe_request_data(request):
    """Read parsed request data without ever decoding raw upload bytes."""
    try:
        data = sanitize(request.data)
    except (UnicodeDecodeError, UnicodeEncodeError):
        data = {"detail": "Request contained binary upload data."}
    except Exception as exc:  # logging must never break an API request
        data = {"detail": f"Unable to log request payload: {exc.__class__.__name__}"}

    try:
        files = {
            str(key): [_file_metadata(item) for item in request.FILES.getlist(key)]
            for key in request.FILES.keys()
        }
        if files:
            if not isinstance(data, dict):
                data = {"data": data}
            data["uploaded_files"] = files
    except Exception:
        pass

    return data


def request_context(request, view=None):
    user = getattr(request, "user", None)
    is_authenticated = bool(user and getattr(user, "is_authenticated", False))
    branch = getattr(user, "branch", None) if is_authenticated else None

    return {
        "method": request.method,
        "path": request.get_full_path(),
        "content_type": getattr(request, "content_type", None),
        "view": view.__class__.__name__ if view else None,
        "action": getattr(view, "action", None) if view else None,
        "user_id": getattr(user, "id", None) if is_authenticated else None,
        "branch_id": getattr(branch, "id", None),
        "query_params": sanitize(request.query_params),
        "request_data": safe_request_data(request),
    }


class APILoggingMixin:
    """Structured request/response/error logging for DRF views and viewsets."""

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
        try:
            context["exception_message"] = str(exc)
        except (UnicodeDecodeError, UnicodeEncodeError):
            context["exception_message"] = "<exception contained binary data>"

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
