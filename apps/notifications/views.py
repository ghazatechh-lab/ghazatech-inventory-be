from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from apps.common.response import ok
from .models import Notification
from .serializers import NotificationSerializer


class NotificationViewSet(ModelViewSet):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, r, pk=None):
        o = self.get_object()
        o.is_read = True
        o.save()
        return ok(NotificationSerializer(o).data)

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, r):
        self.get_queryset().update(is_read=True)
        return ok(message="Notifications marked read")
