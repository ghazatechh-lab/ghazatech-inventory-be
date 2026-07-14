from rest_framework.viewsets import ModelViewSet
from .models import Supplier
from .serializers import SupplierSerializer


class SupplierViewSet(ModelViewSet):
    queryset = Supplier.objects.filter(is_deleted=False)
    serializer_class = SupplierSerializer
    search_fields = ["supplier_code", "supplier_name", "phone", "email"]
    filterset_fields = ["is_active"]

    def perform_destroy(self, obj):
        obj.is_deleted = True
        obj.deleted_by = self.request.user
        obj.save()
