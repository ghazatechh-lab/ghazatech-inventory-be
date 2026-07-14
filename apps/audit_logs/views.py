from rest_framework.viewsets import ReadOnlyModelViewSet
from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogViewSet(ReadOnlyModelViewSet):
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    filterset_fields = ["user", "branch", "module", "action", "created_at"]
