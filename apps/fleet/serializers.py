from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import Vehicle, VehicleDocument, VehicleTrip


class VehicleDocumentSerializer(serializers.ModelSerializer):
    status = serializers.CharField(source="expiry_status", read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = VehicleDocument
        fields = "__all__"
        read_only_fields = ["uploaded_by"]

    def get_file_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get("request")
        url = obj.file.url
        return request.build_absolute_uri(url) if request else url

    def validate_file(self, value):
        if value and value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("Vehicle documents must be 10 MB or smaller.")
        return value


class VehicleSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.branch_name", read_only=True)
    display_name = serializers.SerializerMethodField()
    service_due_soon = serializers.SerializerMethodField()
    vehicle_image_url = serializers.SerializerMethodField()
    documents = VehicleDocumentSerializer(many=True, read_only=True)

    class Meta:
        model = Vehicle
        fields = "__all__"
        extra_kwargs = {"branch": {"required": False}}

    def get_vehicle_image_url(self, obj):
        if not obj.vehicle_image:
            return None
        request = self.context.get("request")
        url = obj.vehicle_image.url
        return request.build_absolute_uri(url) if request else url

    def validate_vehicle_image(self, value):
        if value and value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Vehicle image must be 5 MB or smaller.")
        return value

    def get_display_name(self, obj):
        return f"{obj.make} {obj.model}".strip()

    def get_service_due_soon(self, obj):
        return bool(obj.service_due_km and obj.service_due_km - obj.odometer_km <= 500)


class VehicleTripSerializer(serializers.ModelSerializer):
    vehicle_name = serializers.SerializerMethodField()
    registration_number = serializers.CharField(
        source="vehicle.registration_number",
        read_only=True,
    )
    driver_name = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source="branch.branch_name", read_only=True)
    distance_km = serializers.ReadOnlyField()

    class Meta:
        model = VehicleTrip
        fields = "__all__"
        read_only_fields = [
            "branch",
            "approved_by",
            "actual_return_at",
            "ending_odometer_km",
            "fuel_level_return",
            "return_notes",
            "parking_location",
            "expense_amount",
            "receipt",
            "status",
        ]

    def get_vehicle_name(self, obj):
        return f"{obj.vehicle.make} {obj.vehicle.model}".strip()

    def get_driver_name(self, obj):
        return f"{obj.driver.first_name} {obj.driver.last_name or ''}".strip()

    def validate(self, attrs):
        instance = self.instance
        vehicle = attrs.get("vehicle") or getattr(instance, "vehicle", None)
        driver = attrs.get("driver") or getattr(instance, "driver", None)
        starting_odometer = attrs.get(
            "starting_odometer_km",
            getattr(instance, "starting_odometer_km", None),
        )

        vehicle_changed = bool(
            instance and vehicle and vehicle.pk != instance.vehicle_id
        )

        if vehicle and vehicle.status != "AVAILABLE":
            if instance is None or vehicle_changed:
                raise serializers.ValidationError(
                    {"vehicle": "This vehicle is not available."}
                )

        if vehicle and driver and vehicle.branch_id != driver.branch_id:
            raise serializers.ValidationError(
                {"driver": "Driver and vehicle must belong to the same branch."}
            )

        minimum_odometer = vehicle.odometer_km if vehicle else 0
        if instance and vehicle and vehicle.pk == instance.vehicle_id:
            minimum_odometer = min(
                vehicle.odometer_km,
                instance.starting_odometer_km,
            )

        if (
            vehicle
            and starting_odometer is not None
            and starting_odometer < minimum_odometer
        ):
            raise serializers.ValidationError(
                {
                    "starting_odometer_km": (
                        "Starting odometer cannot be lower than the vehicle odometer."
                    )
                }
            )

        checkout_at = attrs.get(
            "checkout_at",
            getattr(instance, "checkout_at", None),
        )
        expected_return_at = attrs.get(
            "expected_return_at",
            getattr(instance, "expected_return_at", None),
        )
        if expected_return_at and checkout_at and expected_return_at < checkout_at:
            raise serializers.ValidationError(
                {
                    "expected_return_at": (
                        "Expected return cannot be earlier than checkout time."
                    )
                }
            )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        vehicle = validated_data["vehicle"]
        validated_data["branch"] = vehicle.branch
        validated_data["approved_by"] = self.context["request"].user
        trip = super().create(validated_data)

        vehicle.status = "OUT"
        vehicle.odometer_km = trip.starting_odometer_km
        vehicle.save(update_fields=["status", "odometer_km", "updated_at"])
        return trip


class VehicleReturnSerializer(serializers.Serializer):
    actual_return_at = serializers.DateTimeField(
        required=False,
        default=timezone.now,
    )
    ending_odometer_km = serializers.IntegerField(min_value=0)
    fuel_level_return = serializers.ChoiceField(choices=VehicleTrip.FUEL_CHOICES)
    parking_location = serializers.CharField(required=False, allow_blank=True)
    expense_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        default=0,
    )
    return_notes = serializers.CharField(required=False, allow_blank=True)
    receipt = serializers.FileField(required=False, allow_null=True)

    def validate_ending_odometer_km(self, value):
        if value < self.context["trip"].starting_odometer_km:
            raise serializers.ValidationError(
                "Ending odometer cannot be lower than starting odometer."
            )
        return value
