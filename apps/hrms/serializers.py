from rest_framework import serializers
from .models import *


def ser(m):
    return type(
        m.__name__ + "Serializer",
        (serializers.ModelSerializer,),
        {"Meta": type("Meta", (), {"model": m, "fields": "__all__"})},
    )


DepartmentSerializer = ser(Department)
DesignationSerializer = ser(Designation)
EmployeeSerializer = ser(Employee)
EmployeeDocumentSerializer = ser(EmployeeDocument)
AttendanceSerializer = ser(Attendance)
LeaveTypeSerializer = ser(LeaveType)
LeaveRequestSerializer = ser(LeaveRequest)
PayrollSerializer = ser(Payroll)
