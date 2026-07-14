from django.db import models
from apps.common.models import TimeStampedModel


class Shipment(TimeStampedModel):
    shipment_number = models.CharField(max_length=50, unique=True)
    invoice = models.ForeignKey("sales.SalesInvoice", on_delete=models.PROTECT)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT)
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT)
    delivery_address = models.TextField()
    delivery_person = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )
    delivery_date = models.DateField(null=True, blank=True)
    tracking_number = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=30, default="PENDING")
    notes = models.TextField(blank=True)


class ShipmentTrackingLog(TimeStampedModel):
    shipment = models.ForeignKey(
        Shipment, on_delete=models.CASCADE, related_name="tracking_logs"
    )
    status = models.CharField(max_length=30)
    location = models.CharField(max_length=200, blank=True)
    remarks = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL
    )
