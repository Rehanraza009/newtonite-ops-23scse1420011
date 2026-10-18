from django.urls import path
from django.shortcuts import redirect
from . import views

urlpatterns = [
    # Dashboard & Root redirect
    path("", lambda req: redirect("dashboard"), name="root"),
    path("dashboard/", views.dashboard_view, name="dashboard"),

    # Frontend UI routes
    path("items/", views.work_item_list_view, name="work_item_list"),
    path("items/new/", views.work_item_create_view, name="work_item_create"),
    path("items/<int:pk>/", views.work_item_detail_view, name="work_item_detail"),
    path("items/<int:pk>/edit/", views.work_item_edit_view, name="work_item_edit"),

    # REST API endpoints
    path("api/items/", views.work_item_list_create_api, name="api_work_item_list_create"),
    path("api/items/<int:pk>/", views.work_item_detail_update_api, name="api_work_item_detail_update"),
    path("api/items/<int:pk>/claim/", views.work_item_claim_api, name="api_work_item_claim"),
    path("api/items/<int:pk>/transition/", views.work_item_transition_api, name="api_work_item_transition"),
    path("api/items/<int:pk>/activity/", views.work_item_activity_api, name="api_work_item_activity"),
    path("api/items/<int:pk>/comments/", views.work_item_comments_api, name="api_work_item_comments"),
]
