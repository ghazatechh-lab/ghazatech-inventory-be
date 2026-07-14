from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from .models import *
from .serializers import *
from .services import confirm_grn
from apps.common.response import ok


class Base(ModelViewSet):
    def perform_create(self, s):
        s.save(
            created_by=self.request.user,
            updated_by=self.request.user,
            branch=s.validated_data.get("branch") or self.request.user.branch,
        )


class PurchaseOrderViewSet(Base):
    queryset = PurchaseOrder.objects.all()
    serializer_class = POSerializer
    filterset_fields = ["branch", "supplier", "status"]


class GRNViewSet(Base):
    queryset = GoodsReceivedNote.objects.all()
    serializer_class = GRNSerializer
    filterset_fields = ["branch", "supplier", "status"]

    @action(detail=True, methods=["post"])
    def confirm(self, r, pk=None):
        return ok(
            GRNSerializer(confirm_grn(self.get_object(), r.user)).data,
            "GRN confirmed successfully",
        )


class SupplierBillViewSet(Base):
    queryset = SupplierBill.objects.all()
    serializer_class = SupplierBillSerializer


class SupplierPaymentViewSet(Base):
    queryset = SupplierPayment.objects.all()
    serializer_class = SupplierPaymentSerializer


class SupplierReturnViewSet(Base):
    queryset = SupplierReturn.objects.all()
    serializer_class = SupplierReturnSerializer
