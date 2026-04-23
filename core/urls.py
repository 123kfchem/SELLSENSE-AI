from django.urls import path
from .views import (
    BusinessLoginView,
    business_register,
    business_logout,
    employee_dashboard,
    employer_dashboard,
    home,
    reports_view,
    role_select,
)

urlpatterns = [
    path("", home, name="home"),
    path("login/", BusinessLoginView.as_view(), name="login"),
    path("register-business/", business_register, name="business-register"),
    path("logout/", business_logout, name="logout"),
    path("role-select/", role_select, name="role-select"),
    path("employer/", employer_dashboard, name="employer-dashboard"),
    path("employee/", employee_dashboard, name="employee-dashboard"),
    path("reports/<str:period>/", reports_view, name="reports"),
]
