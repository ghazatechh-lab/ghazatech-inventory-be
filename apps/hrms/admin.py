from django.contrib import admin
from .models import *

admin.site.register(Department)
admin.site.register(Designation)
admin.site.register(Employee)
admin.site.register(EmployeeDocument)
admin.site.register(Attendance)
admin.site.register(LeaveType)
admin.site.register(LeaveBalance)
admin.site.register(LeaveRequest)
admin.site.register(SalaryRevision)
admin.site.register(PayrollRun)
admin.site.register(PayrollEntry)
