import csv

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from datetime import timedelta

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.audit_logs.models import AuditLog

from .models import RecoveryRecord, RecoverySettings
from .serializers import RecoveryRecordSerializer, RecoverySettingsSerializer


class RecoveryRecordViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RecoveryRecordSerializer
    search_fields = [
        "record_name",
        "reference",
        "module",
        "model_name",
        "deletion_reason",
        "deleted_by__full_name",
        "deleted_by__email",
    ]
    filterset_fields = ["module", "branch", "status"]
    ordering_fields = ["deleted_at", "expires_at", "record_name", "module"]
    ordering = ["-deleted_at"]
    permission_map = {
        "list": "settings.recovery.view",
        "retrieve": "settings.recovery.view",
        "summary": "settings.recovery.view",
        "activity": "settings.recovery.view",
        "export": "settings.recovery.export",
        "restore": "settings.recovery.restore",
        "bulk_restore": "settings.recovery.restore",
        "permanent_delete": "settings.recovery.permanent_delete",
        "bulk_delete": "settings.recovery.permanent_delete",
    }

    def get_queryset(self):
        queryset = RecoveryRecord.objects.select_related(
            "deleted_by",
            "restored_by",
            "permanently_deleted_by",
            "branch",
            "content_type",
        )
        status_param = self.request.query_params.get("status")
        if not status_param:
            queryset = queryset.filter(status=RecoveryRecord.STATUS_DELETED)
        q = self.request.query_params.get("q", "").strip()
        if q:
            queryset = queryset.filter(
                Q(record_name__icontains=q)
                | Q(reference__icontains=q)
                | Q(module__icontains=q)
                | Q(deletion_reason__icontains=q)
                | Q(deleted_by__full_name__icontains=q)
                | Q(deleted_by__email__icontains=q)
            )
        return queryset

    def _get_object_instance(self, record):
        if not record.content_type:
            return None
        model_class = record.content_type.model_class()
        if model_class is None:
            return None
        return model_class._default_manager.filter(pk=record.object_id).first()

    def _hard_delete_employee(self, employee):
        """
        Permanently remove an Employee and employee-owned related records.

        Some HRMS relations intentionally use PROTECT for normal operations.
        Permanent deletion from Recovery Centre is an explicit destructive
        action, so those employee-owned rows are removed first.
        """
        # Delete direct loan repayments before their protected parent loans.
        for related_name in [
            "loan_repayments",
            "documents",
            "attendance_records",
            "leave_balances",
            "leave_requests",
            "salary_revisions",
            "salary_advances",
            "payroll_entries",
            "salary_certificates",
            "employee_letters",
            "vehicle_trips",
            "service_jobs",
        ]:
            manager = getattr(employee, related_name, None)
            if manager is not None:
                manager.all().delete()

        # EmployeeLoanRepayment also references EmployeeLoan with PROTECT, so
        # employee loans must be removed after repayments.
        loans = getattr(employee, "employee_loans", None)
        if loans is not None:
            for loan in list(loans.all()):
                repayments = getattr(loan, "repayments", None)
                if repayments is not None:
                    repayments.all().delete()
                loan.delete()

        # The linked User has SET_NULL to Employee, so keep the account row but
        # remove its employee link during Employee deletion. It remains inactive.
        linked_user = getattr(employee, "user", None)
        if linked_user is not None and linked_user.is_active:
            linked_user.is_active = False
            linked_user.save(update_fields=["is_active"])

        employee.delete()

    def _restore_record(self, record, user):
        if record.status != RecoveryRecord.STATUS_DELETED:
            raise ValidationError({"detail": "Only deleted records can be restored."})
        instance = self._get_object_instance(record)
        if instance is None:
            raise ValidationError(
                {"detail": "The original database record no longer exists."}
            )
        if hasattr(instance, "is_deleted"):
            instance.is_deleted = False
            update_fields = ["is_deleted"]
            if hasattr(instance, "deleted_at"):
                instance.deleted_at = None
                update_fields.append("deleted_at")
            if hasattr(instance, "deleted_by"):
                instance.deleted_by = None
                update_fields.append("deleted_by")
            if hasattr(instance, "updated_at"):
                update_fields.append("updated_at")
            instance.save(update_fields=update_fields)
        elif record.module == "hrms" and record.model_name == "employee":
            # Employee was never modified when moved to Recovery Centre, so
            # preserve its original is_active/employment_status values.
            linked_user = getattr(instance, "user", None)
            if linked_user and not linked_user.is_active:
                linked_user.is_active = True
                linked_user.save(update_fields=["is_active"])
        else:
            raise ValidationError(
                {"detail": "This record type does not support recovery."}
            )

        record.status = RecoveryRecord.STATUS_RESTORED
        record.restored_at = timezone.now()
        record.restored_by = user
        record.save(
            update_fields=["status", "restored_at", "restored_by", "updated_at"]
        )

        AuditLog.objects.create(
            user=user,
            branch=record.branch,
            module="recovery",
            action="restore",
            description=f"{record.reference or record.record_name} restored from Recovery Centre.",
            object_type=f"{record.module}.{record.model_name}",
            object_id=record.object_id,
            after_values=record.snapshot,
        )
        return record

    def _permanent_delete_record(self, record, user):
        if record.status != RecoveryRecord.STATUS_DELETED:
            raise ValidationError(
                {"detail": "Only deleted records can be permanently deleted."}
            )
        instance = self._get_object_instance(record)
        if instance is not None:
            try:
                if record.module == "hrms" and record.model_name == "employee":
                    self._hard_delete_employee(instance)
                else:
                    instance.delete()
            except ProtectedError as exc:
                raise ValidationError(
                    {
                        "detail": (
                            "This record is referenced by protected transactions "
                            "and cannot be permanently deleted."
                        )
                    }
                ) from exc

        record.status = RecoveryRecord.STATUS_PERMANENT
        record.permanently_deleted_at = timezone.now()
        record.permanently_deleted_by = user
        record.save(
            update_fields=[
                "status",
                "permanently_deleted_at",
                "permanently_deleted_by",
                "updated_at",
            ]
        )
        AuditLog.objects.create(
            user=user,
            branch=record.branch,
            module="recovery",
            action="permanent_delete",
            description=f"{record.reference or record.record_name} permanently deleted from Recovery Centre.",
            object_type=f"{record.module}.{record.model_name}",
            object_id=record.object_id,
            before_values=record.snapshot,
        )
        return record

    @action(detail=False, methods=["get"])
    def summary(self, request):
        now = timezone.now()
        current = RecoveryRecord.objects.filter(status=RecoveryRecord.STATUS_DELETED)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return Response(
            {
                "total_deleted": current.count(),
                "deleted_today": current.filter(
                    deleted_at__date=timezone.localdate()
                ).count(),
                "restored_this_month": RecoveryRecord.objects.filter(
                    status=RecoveryRecord.STATUS_RESTORED,
                    restored_at__gte=month_start,
                ).count(),
                "expiring_soon": current.filter(
                    expires_at__isnull=False,
                    expires_at__lte=now + timedelta(days=7),
                    expires_at__gte=now,
                ).count(),
                "permanent_deletes": RecoveryRecord.objects.filter(
                    status=RecoveryRecord.STATUS_PERMANENT
                ).count(),
            }
        )

    @action(detail=False, methods=["get"])
    def activity(self, request):
        queryset = RecoveryRecord.objects.exclude(
            status=RecoveryRecord.STATUS_DELETED
        ).select_related(
            "deleted_by", "restored_by", "permanently_deleted_by", "branch"
        )[
            :100
        ]
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=False, methods=["get"])
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            'attachment; filename="recovery-centre-log.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(
            [
                "Record",
                "Module",
                "Reference",
                "Branch",
                "Deleted By",
                "Deleted At",
                "Reason",
                "Expires At",
            ]
        )
        for record in queryset:
            writer.writerow(
                [
                    record.record_name,
                    record.module,
                    record.reference,
                    record.branch.branch_name if record.branch else "",
                    record.deleted_by.full_name if record.deleted_by else "System",
                    record.deleted_at.isoformat() if record.deleted_at else "",
                    record.deletion_reason,
                    record.expires_at.isoformat() if record.expires_at else "",
                ]
            )
        return response

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def restore(self, request, pk=None):
        record = self.get_object()
        self._restore_record(record, request.user)
        return Response(self.get_serializer(record).data)

    @action(detail=True, methods=["delete"], url_path="permanent-delete")
    @transaction.atomic
    def permanent_delete(self, request, pk=None):
        record = self.get_object()
        self._permanent_delete_record(record, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="bulk-restore")
    @transaction.atomic
    def bulk_restore(self, request):
        ids = request.data.get("ids") or []
        if not ids:
            raise ValidationError({"ids": "Select at least one recovery record."})
        records = list(RecoveryRecord.objects.filter(pk__in=ids))
        for record in records:
            self._restore_record(record, request.user)
        return Response({"restored": len(records)})

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    @transaction.atomic
    def bulk_delete(self, request):
        ids = request.data.get("ids") or []
        if not ids:
            raise ValidationError({"ids": "Select at least one recovery record."})
        records = list(RecoveryRecord.objects.filter(pk__in=ids))
        for record in records:
            self._permanent_delete_record(record, request.user)
        return Response({"deleted": len(records)})


class RecoverySettingsViewSet(viewsets.ViewSet):
    permission_map = {
        "current": "settings.recovery.view",
    }

    @action(detail=False, methods=["get", "patch"], url_path="current")
    def current(self, request):
        obj = RecoverySettings.current()
        if request.method == "PATCH":
            if not (
                request.user.is_superuser
                or (request.user.role and request.user.role.code == "ADMIN")
                or request.user.has_operation_permission("settings.recovery.edit")
            ):
                return Response(
                    {
                        "detail": "You do not have permission to change recovery settings."
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            serializer = RecoverySettingsSerializer(
                obj,
                data=request.data,
                partial=True,
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        return Response(RecoverySettingsSerializer(obj).data)
