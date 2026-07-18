import logging

from rest_framework.views import exception_handler

from .logging import request_context, sanitize

logger = logging.getLogger("ghazatech.api")


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    request = context.get("request")
    view = context.get("view")

    log_context = request_context(request, view) if request else {}
    log_context.update(
        {
            "exception_type": exc.__class__.__name__,
            "exception_message": str(exc),
            "status_code": getattr(response, "status_code", 500),
        }
    )

    if response is not None:
        log_context["errors"] = sanitize(response.data)
        logger.warning("DRF exception response | %s", log_context)

        response.data = {
            "success": False,
            "message": (
                "Validation failed" if response.status_code == 400 else "Request failed"
            ),
            "errors": response.data,
        }
        return response

    logger.exception("Unhandled DRF exception | %s", log_context, exc_info=exc)
    return None
