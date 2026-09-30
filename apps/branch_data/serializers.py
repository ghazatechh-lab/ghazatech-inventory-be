from rest_framework import serializers

from .models import BranchDatabaseProfile, MasterInventorySyncLog


class BranchDatabaseProfileSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.branch_name", read_only=True)
    branch_code = serializers.CharField(source="branch.branch_code", read_only=True)

    class Meta:
        model = BranchDatabaseProfile
        fields = "__all__"


class MasterInventorySyncLogSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.product_name", read_only=True)
    source_branch_name = serializers.CharField(
        source="source_branch.branch_name", read_only=True
    )
    master_branch_name = serializers.CharField(
        source="master_branch.branch_name", read_only=True
    )

    class Meta:
        model = MasterInventorySyncLog
        fields = "__all__"
        read_only_fields = fields
