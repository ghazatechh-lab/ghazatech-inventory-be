"""Fallback audit and read enrichment for API views without AuditedModelViewSet."""
import logging
from rest_framework_simplejwt.authentication import JWTAuthentication
from .actor_tracking import annotate_response, record_event

logger = logging.getLogger(__name__)


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def _annotate(self, request, response):
        """Compatibility with earlier category-audit patch."""
        return annotate_response(request, response)

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith('/api/') or not (200 <= response.status_code < 300):
            return response
        drf_request = (getattr(response, 'renderer_context', None) or {}).get('request')
        try:
            if request.method in ('POST', 'PUT', 'PATCH') and not getattr(response, '_api_actor_recorded', False):
                view = (getattr(response, 'renderer_context', None) or {}).get('view')
                action = getattr(view, 'action', '')
                if action in ('create', 'update', 'partial_update'):
                    actor = getattr(drf_request, 'user', None) if drf_request else None
                    if not getattr(actor, 'is_authenticated', False):
                        result = JWTAuthentication().authenticate(request)
                        actor = result[0] if result else None
                    record_event(drf_request or request, response,
                                 action='CREATED' if action == 'create' else 'UPDATED',
                                 actor=actor)
            # Read enrichment also handles generic views and previously modified
            # viewsets; never modify Recovery Centre's Deleted By display.
            if request.method == 'GET':
                annotate_response(drf_request or request, response)
        except Exception:
            logger.exception('Audit middleware failed for %s %s', request.method, request.path)
        return response
