import logging
import re
from collections.abc import Mapping, Sequence

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    MethodNotAllowed,
    NotAuthenticated,
    NotFound,
    ParseError,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .logging import request_context, sanitize

logger = logging.getLogger("ghazatech.api")


def _humanize(field):
    return str(field or "field").replace("_", " ").replace(".", " ").title()


def _friendly_message(field, message, code=None):
    """Convert DRF/internal validation text into user-friendly wording."""
    label = _humanize(field)
    text = str(message or "").strip()
    lowered = text.lower()
    code = str(code or "").lower()

    if code == "required" or lowered == "this field is required.":
        return f"{label} is required."

    if (
        code in {"null", "blank"}
        or "may not be null" in lowered
        or "may not be blank" in lowered
    ):
        return f"{label} is required."

    if code in {"does_not_exist", "incorrect_type", "invalid_choice"}:
        return f"Select a valid {label.lower()}."

    if "invalid pk" in lowered or "object does not exist" in lowered:
        return f"Select a valid {label.lower()}."

    if "expected pk value" in lowered:
        return f"Select a valid {label.lower()}."

    if code == "unique" or "already exists" in lowered or "must be unique" in lowered:
        return f"{label} already exists. Please use a different value."

    if code in {"invalid", "invalid_email"} and "email" in str(field).lower():
        return "Enter a valid email address."

    if "valid email" in lowered:
        return "Enter a valid email address."

    if "valid integer" in lowered or "valid number" in lowered:
        return f"Enter a valid number for {label.lower()}."

    if "greater than or equal" in lowered:
        match = re.search(r"greater than or equal to\s+([^\.]+)", lowered)
        return f"{label} must be at least {match.group(1) if match else 'the minimum allowed value'}."

    if "less than or equal" in lowered:
        match = re.search(r"less than or equal to\s+([^\.]+)", lowered)
        return f"{label} must not exceed {match.group(1) if match else 'the maximum allowed value'}."

    if "no more than" in lowered and "characters" in lowered:
        number = re.search(r"no more than\s+(\d+)", lowered)
        return f"{label} must contain no more than {number.group(1) if number else 'the allowed number of'} characters."

    if "at least" in lowered and "characters" in lowered:
        number = re.search(r"at least\s+(\d+)", lowered)
        return f"{label} must contain at least {number.group(1) if number else 'the required number of'} characters."

    if code == "invalid_image" or "valid image" in lowered:
        return f"Upload a valid image for {label.lower()}."

    if code == "empty" or "submitted file is empty" in lowered:
        return f"The uploaded {label.lower()} file is empty."

    if code == "max_size" or "file size" in lowered:
        return f"The uploaded {label.lower()} file is too large."

    # Avoid leaking serializer/internal terminology.
    text = re.sub(r"ErrorDetail\([^)]*\)", "", text).strip()
    text = text.replace("This field", label)
    return text or f"Enter a valid value for {label.lower()}."


def _normalize_errors(value, path=""):
    """Return JSON-safe, user-friendly validation errors."""
    if isinstance(value, Mapping):
        normalized = {}
        for key, item in value.items():
            next_path = (
                path
                if key in {"non_field_errors", "detail"}
                else (f"{path}.{key}" if path else str(key))
            )
            normalized[key] = _normalize_errors(item, next_path)
        return normalized

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result = []
        for item in value:
            if isinstance(item, (Mapping, list, tuple)):
                result.append(_normalize_errors(item, path))
            else:
                result.append(
                    _friendly_message(path, item, getattr(item, "code", None))
                )
        return result

    return _friendly_message(path, value, getattr(value, "code", None))


def _first_error(value, path=""):
    if isinstance(value, Mapping):
        for key, item in value.items():
            next_path = (
                path
                if key in {"non_field_errors", "detail"}
                else (f"{path}.{key}" if path else str(key))
            )
            message = _first_error(item, next_path)
            if message:
                return message
        return None

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            message = _first_error(item, path)
            if message:
                return message
        return None

    return _friendly_message(path, value, getattr(value, "code", None))


def _error_response(
    message, errors=None, status_code=status.HTTP_400_BAD_REQUEST, code=None
):
    payload = {
        "success": False,
        "message": message,
        "errors": errors or {},
    }
    if code:
        payload["code"] = code
    return Response(payload, status=status_code)


def custom_exception_handler(exc, context):
    request = context.get("request")
    view = context.get("view")
    log_context = request_context(request, view) if request else {}
    log_context.update(
        {
            "exception_type": exc.__class__.__name__,
            "exception_message": str(exc),
        }
    )

    if isinstance(exc, UnicodeDecodeError):
        message = (
            "The uploaded file could not be processed. "
            "Please select a valid JPG, PNG, or WebP image and try again."
        )
        logger.warning(
            "Binary upload decode error | %s",
            {**log_context, "status_code": 400},
        )
        return _error_response(
            message,
            {"product_image": [message]},
            status.HTTP_400_BAD_REQUEST,
            "invalid_upload",
        )

    if isinstance(exc, ProtectedError):
        message = "This record cannot be deleted because it is used by other records."
        logger.warning(
            "Protected delete blocked | %s", {**log_context, "status_code": 409}
        )
        return _error_response(
            message, {"detail": [message]}, status.HTTP_409_CONFLICT, "protected_record"
        )

    if isinstance(exc, IntegrityError):
        message = "This record conflicts with existing data. Check for duplicate values or related records."
        logger.exception(
            "Database integrity error | %s", {**log_context, "status_code": 409}
        )
        return _error_response(
            message, {"detail": [message]}, status.HTTP_409_CONFLICT, "integrity_error"
        )

    if isinstance(exc, ObjectDoesNotExist):
        message = "The requested record was not found."
        logger.warning("Object not found | %s", {**log_context, "status_code": 404})
        return _error_response(
            message, {"detail": [message]}, status.HTTP_404_NOT_FOUND, "not_found"
        )

    response = exception_handler(exc, context)

    if response is not None:
        original_errors = response.data
        friendly_errors = _normalize_errors(original_errors)
        message = _first_error(original_errors)

        if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
            message = (
                "Your login session is invalid or has expired. Please sign in again."
            )
        elif isinstance(exc, PermissionDenied):
            message = "You do not have permission to perform this action."
        elif isinstance(exc, NotFound):
            message = "The requested record was not found."
        elif isinstance(exc, MethodNotAllowed):
            message = "This action is not supported."
        elif isinstance(exc, ParseError):
            message = "The submitted information could not be read. Please check the form and try again."
        elif isinstance(exc, Throttled):
            message = "Too many attempts. Please wait and try again."
        elif isinstance(exc, ValidationError):
            message = message or "Please correct the highlighted fields and try again."

        log_context.update(
            {
                "status_code": response.status_code,
                "errors": sanitize(original_errors),
            }
        )
        if response.status_code >= 500:
            logger.exception("DRF server exception | %s", log_context, exc_info=exc)
        else:
            logger.warning("DRF request exception | %s", log_context)

        response.data = {
            "success": False,
            "message": message or "The request could not be completed.",
            "errors": friendly_errors,
            "code": getattr(exc, "default_code", None) or exc.__class__.__name__,
        }
        return response

    message = (
        "An unexpected server error occurred. Please try again or contact support."
    )
    logger.exception(
        "Unhandled API exception | %s",
        {**log_context, "status_code": 500},
        exc_info=exc,
    )
    return _error_response(
        message,
        {"detail": [message]},
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "server_error",
    )
