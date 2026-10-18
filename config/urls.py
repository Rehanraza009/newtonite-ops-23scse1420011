"""
URL configuration for Newtonite Operations Hub project.
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.db import connection


def health_check(request):
    """Health check endpoint verifying database connectivity."""
    db_ok = True
    db_error = None
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        db_ok = False
        db_error = str(exc)

    status_code = 200 if db_ok else 503
    return JsonResponse(
        {
            "status": "healthy" if db_ok else "unhealthy",
            "database": "connected" if db_ok else "disconnected",
            "database_vendor": connection.vendor,
            "error": db_error,
        },
        status=status_code,
    )


urlpatterns = [
    path("admin/", admin.site.urls),
    # Health checks
    path("health/", health_check, name="health_check"),
    path("api/health/", health_check, name="api_health_check"),
    # Accounts & Authentication
    path("", include("accounts.urls")),
    # Teams
    path("", include("teams.urls")),
    # Work Items
    path("", include("workitems.urls")),
]
