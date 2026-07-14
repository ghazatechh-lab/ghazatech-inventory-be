from rest_framework.viewsets import ModelViewSet
from .models import Branch
from .serializers import BranchSerializer


class BranchViewSet(ModelViewSet):
    queryset = Branch.objects.all()
    serializer_class = BranchSerializer
    search_fields = ["branch_code", "branch_name", "city"]
    filterset_fields = ["is_active", "emirate"]
