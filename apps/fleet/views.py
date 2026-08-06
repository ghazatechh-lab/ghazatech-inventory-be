from django.db import transaction
from django.db.models import Count, Q
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.viewsets import ModelViewSet

from apps.common.response import ok

from .models import Vehicle, VehicleTrip
from .serializers import (
    VehicleReturnSerializer,
    VehicleSerializer,
    VehicleTripSerializer,
)


class VehicleViewSet(ModelViewSet):
    queryset = Vehicle.objects.select_related("branch").all()
    serializer_class = VehicleSerializer
    filterset_fields = ["branch", "status", "vehicle_type"]
    search_fields = ["vehicle_code", "make", "model", "registration_number"]
    ordering_fields = [
        "make",
        "model",
        "registration_number",
        "odometer_km",
        "created_at",
    ]

    @action(detail=False, methods=["get"])
    def dashboard(self, request):
        qs = self.filter_queryset(self.get_queryset())
        counts = qs.aggregate(
            total=Count("id"),
            available=Count("id", filter=Q(status="AVAILABLE")),
            currently_out=Count("id", filter=Q(status="OUT")),
        )
        counts["service_due"] = sum(
            1
            for vehicle in qs
            if vehicle.service_due_km
            and vehicle.service_due_km - vehicle.odometer_km <= 500
        )
        counts["active_trips"] = VehicleTripSerializer(
            VehicleTrip.objects.select_related(
                "vehicle", "driver", "branch", "approved_by"
            ).filter(vehicle__in=qs, status="ACTIVE"),
            many=True,
            context={"request": request},
        ).data
        counts["vehicles"] = VehicleSerializer(
            qs, many=True, context={"request": request}
        ).data
        return ok(counts)


class VehicleTripViewSet(ModelViewSet):
    queryset = VehicleTrip.objects.select_related(
        "vehicle", "driver", "branch", "approved_by"
    ).all()
    serializer_class = VehicleTripSerializer
    filterset_fields = ["branch", "vehicle", "driver", "status"]
    search_fields = [
        "vehicle__registration_number",
        "vehicle__make",
        "vehicle__model",
        "driver__first_name",
        "driver__last_name",
        "purpose",
        "destination",
    ]
    ordering_fields = [
        "checkout_at",
        "expected_return_at",
        "actual_return_at",
        "expense_amount",
        "created_at",
    ]

    @transaction.atomic
    def perform_update(self, serializer):
        trip = self.get_object()
        old_vehicle = trip.vehicle
        new_vehicle = serializer.validated_data.get("vehicle", old_vehicle)

        if trip.status == "ACTIVE" and new_vehicle.pk != old_vehicle.pk:
            if new_vehicle.status != "AVAILABLE":
                raise serializers.ValidationError(
                    {"vehicle": "The selected vehicle is not available."}
                )

            old_vehicle.status = "AVAILABLE"
            old_vehicle.save(update_fields=["status", "updated_at"])

            new_vehicle.status = "OUT"
            new_vehicle.save(update_fields=["status", "updated_at"])

        serializer.save(branch=new_vehicle.branch)

    @transaction.atomic
    def perform_destroy(self, instance):
        vehicle = instance.vehicle
        was_active = instance.status == "ACTIVE"
        instance.delete()

        if was_active and not vehicle.trips.filter(status="ACTIVE").exists():
            vehicle.status = "AVAILABLE"
            vehicle.save(update_fields=["status", "updated_at"])

    @action(detail=True, methods=["post"], url_path="return-vehicle")
    @transaction.atomic
    def return_vehicle(self, request, pk=None):
        trip = self.get_object()
        if trip.status != "ACTIVE":
            raise serializers.ValidationError(
                {"status": "Only an active trip can be returned."}
            )

        serializer = VehicleReturnSerializer(
            data=request.data,
            context={"trip": trip},
        )
        serializer.is_valid(raise_exception=True)

        for field, value in serializer.validated_data.items():
            setattr(trip, field, value)

        trip.status = "RETURNED"
        trip.save()

        trip.vehicle.status = "AVAILABLE"
        trip.vehicle.odometer_km = trip.ending_odometer_km
        trip.vehicle.save(update_fields=["status", "odometer_km", "updated_at"])

        return ok(
            VehicleTripSerializer(trip, context={"request": request}).data,
            message="Vehicle returned successfully",
        )
