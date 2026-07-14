from rest_framework.routers import DefaultRouter
from .views import BranchViewSet

r = DefaultRouter()
r.register("", BranchViewSet, basename="branch")
urlpatterns = r.urls
