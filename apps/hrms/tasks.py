from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import Employee, EmployeeDocument
from apps.notifications.services import notify_branch


@shared_task
def check_document_expiry():
    today = timezone.localdate()
    fields = [
        "passport_expiry_date",
        "visa_expiry_date",
        "emirates_id_expiry_date",
        "labour_card_expiry_date",
        "driving_license_expiry_date",
        "insurance_expiry_date",
    ]
    created = 0
    for e in Employee.objects.filter(status="ACTIVE"):
        for field in fields:
            expiry = getattr(e, field)
            if expiry and expiry <= today + timedelta(days=60):
                days = (expiry - today).days
                priority = "URGENT" if days < 0 or days <= 7 else "WARNING"
                notify_branch(
                    e.branch,
                    "DOCUMENT_EXPIRY",
                    f'{field.replace("_"," ").title()}',
                    f"{e.full_name}: expires in {days} day(s).",
                    priority,
                )
                created += 1
    return created
