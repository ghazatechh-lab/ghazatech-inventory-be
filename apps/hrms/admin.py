from django.contrib import admin
from .models import *

admin.site.register(
    [
        Department,
        Designation,
        Employee,
        EmployeeDocument,
        Attendance,
        LeaveType,
        LeaveRequest,
        Payroll,
    ]
)
