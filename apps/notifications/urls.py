from rest_framework.routers import DefaultRouter
from .views import NotificationViewSet

r = DefaultRouter()
r.register("", NotificationViewSet, basename="notification")
urlpatterns = r.urls
