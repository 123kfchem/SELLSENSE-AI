from django.urls import path
from .views import (
    BusinessLoginView,
    business_logout,
    daily_sales_pdf,
    employee_dashboard,
    employer_dashboard,
    home,
    reports_view,
    role_select,
    sales_analytics_api,
    stock_insights_api,
    superuser_business_stats_api,
    superuser_dashboard,
)

urlpatterns = [
    path("", home, name="home"),
    path("login/", BusinessLoginView.as_view(), name="login"),
    path("superuser/", superuser_dashboard, name="superuser-dashboard"),
    path("logout/", business_logout, name="logout"),
    path("role-select/", role_select, name="role-select"),
    path("employer/", employer_dashboard, name="employer-dashboard"),
    path("employer/daily-sales/pdf/", daily_sales_pdf, name="daily-sales-pdf"),
    path("employee/", employee_dashboard, name="employee-dashboard"),
    path("reports/<str:period>/", reports_view, name="reports"),
    path("api/analytics/sales/", sales_analytics_api, name="sales-analytics-api"),
    path("api/analytics/stock/", stock_insights_api, name="stock-insights-api"),
    path("api/superuser/business-stats/", superuser_business_stats_api, name="superuser-business-stats-api"),
]
