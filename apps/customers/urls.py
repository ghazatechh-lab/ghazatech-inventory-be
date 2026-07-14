from rest_framework.routers import DefaultRouter
from .views import CustomerViewSet

r = DefaultRouter()
r.register("", CustomerViewSet, basename="customer")

urlpatterns = r.urls
