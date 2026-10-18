from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response


def login_view(request):
    """Handles user login via HTML form and AJAX."""
    if request.user.is_authenticated:
        return redirect("dashboard")

    error_message = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get("next") or request.POST.get("next") or "/dashboard/"
            if request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", ""):
                return JsonResponse({"status": "ok", "redirect": next_url})
            return redirect(next_url)
        else:
            error_message = "Invalid username or password. Please try again."
            if request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", ""):
                return JsonResponse({"error": error_message}, status=401)

    return render(request, "accounts/login.html", {"error": error_message})


@require_http_methods(["GET", "POST"])
def logout_view(request):
    """Logs out the current user and redirects to login."""
    logout(request)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"status": "ok", "redirect": "/login/"})
    return redirect("login")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def whoami_view(request):
    """Returns profile and team memberships for the currently authenticated user."""
    from teams.models import TeamMembership
    memberships = TeamMembership.objects.filter(user=request.user).select_related("team")
    teams_data = [
        {
            "team_id": m.team.id,
            "team_name": m.team.name,
            "team_slug": m.team.slug,
            "role": m.role,
            "is_restricted": m.team.is_restricted,
        }
        for m in memberships
    ]

    return Response(
        {
            "id": request.user.id,
            "username": request.user.username,
            "full_name": request.user.get_full_name(),
            "email": request.user.email,
            "job_title": request.user.job_title,
            "is_superuser": request.user.is_superuser,
            "teams": teams_data,
        }
    )
