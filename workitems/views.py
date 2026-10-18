from django.db.models import Q
from django.shortcuts import render, get_object_or_404, redirect
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from teams.models import Team, TeamMembership, TeamRole
from teams.permissions import TeamPermissionService
from .models import (
    WorkItem,
    WorkItemStatus,
    WorkItemPriority,
    WorkItemType,
    Comment,
    ActivityEvent,
)
from .serializers import (
    WorkItemListSerializer,
    WorkItemDetailSerializer,
    WorkItemCreateSerializer,
    WorkItemUpdateSerializer,
    TransitionActionSerializer,
    CommentSerializer,
    ActivityEventSerializer,
)
from .services import (
    WorkItemService,
    ConflictError,
    StaleUpdateConflictError,
    ALLOWED_TRANSITIONS,
)


def get_visible_workitems_queryset(user):
    """
    Returns queryset of WorkItems visible to the user.
    - Superusers see all items.
    - Authenticated users see items from non-restricted teams,
      PLUS items from restricted teams where they have active membership.
    """
    if not user or not user.is_authenticated:
        return WorkItem.objects.none()

    if user.is_superuser:
        return WorkItem.objects.all().select_related("team", "assignee", "creator")

    user_team_ids = TeamMembership.objects.filter(user=user).values_list("team_id", flat=True)
    return (
        WorkItem.objects.filter(
            Q(team__is_restricted=False) | Q(team_id__in=user_team_ids)
        )
        .distinct()
        .select_related("team", "assignee", "creator")
    )


# ============================================================================
# API VIEWS
# ============================================================================

class WorkItemPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def work_item_list_create_api(request):
    """
    GET /api/items/
    List work items with server-side search, filtering, and deterministic pagination.

    POST /api/items/
    Create a new work item with Idempotency-Key support.
    """
    if request.method == "GET":
        qs = get_visible_workitems_queryset(request.user)

        # Server-side search on title and description
        search_query = request.query_params.get("q", "").strip()
        if search_query:
            qs = qs.filter(Q(title__icontains=search_query) | Q(description__icontains=search_query))

        # Filters
        team_param = request.query_params.get("team")
        if team_param:
            qs = qs.filter(team_id=team_param)

        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        priority_param = request.query_params.get("priority")
        if priority_param:
            qs = qs.filter(priority=priority_param)

        type_param = request.query_params.get("type")
        if type_param:
            qs = qs.filter(type=type_param)

        assignee_param = request.query_params.get("assignee")
        if assignee_param:
            if assignee_param == "unassigned":
                qs = qs.filter(assignee__isnull=True)
            elif assignee_param == "me":
                qs = qs.filter(assignee=request.user)
            else:
                qs = qs.filter(assignee_id=assignee_param)

        # Deterministic sorting
        sort_param = request.query_params.get("ordering", "-created_at")
        allowed_sorts = {
            "-created_at": ["-created_at", "-id"],
            "created_at": ["created_at", "id"],
            "-priority": ["-priority", "-created_at", "-id"],
            "priority": ["priority", "-created_at", "-id"],
            "due_date": ["due_date", "-created_at", "-id"],
        }
        qs = qs.order_by(*allowed_sorts.get(sort_param, ["-created_at", "-id"]))

        paginator = WorkItemPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = WorkItemListSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    elif request.method == "POST":
        idempotency_key = request.headers.get("Idempotency-Key") or request.data.get("idempotency_key")
        serializer = WorkItemCreateSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            item_data, is_replay = WorkItemService.create_item(
                user=request.user,
                validated_data=serializer.validated_data,
                idempotency_key=idempotency_key,
            )
            response_status = status.HTTP_200_OK if is_replay else status.HTTP_201_CREATED
            resp = Response(item_data, status=response_status)
            if is_replay:
                resp["Idempotent-Replay"] = "true"
            return resp
        except PermissionDenied as pe:
            return Response({"error": "Forbidden", "message": str(pe)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return Response({"error": "Bad Request", "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def work_item_detail_update_api(request, pk):
    """
    GET /api/items/<id>/
    Retrieve work item detail.

    PATCH /api/items/<id>/
    Update permitted fields with optimistic locking version verification.
    """
    qs = get_visible_workitems_queryset(request.user)
    try:
        item = qs.get(pk=pk)
    except WorkItem.DoesNotExist:
        return Response({"error": "Not Found", "message": "Work item not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        serializer = WorkItemDetailSerializer(item, context={"request": request})
        return Response(serializer.data)

    elif request.method == "PATCH":
        # Check If-Match header or body version
        version = request.headers.get("If-Match")
        if version:
            version = version.strip('"')
        if not version:
            version = request.data.get("version")

        serializer = WorkItemUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            updated_item = WorkItemService.update_item(
                work_item_id=pk,
                user=request.user,
                data=serializer.validated_data,
                expected_version=version,
            )
            resp_serializer = WorkItemDetailSerializer(updated_item, context={"request": request})
            return Response(resp_serializer.data)
        except StaleUpdateConflictError as se:
            return Response(
                {
                    "error": "Conflict",
                    "code": "STALE_UPDATE",
                    "message": se.message,
                    "current_version": se.current_version,
                    "latest_data": se.latest_data,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except PermissionDenied as pe:
            return Response({"error": "Forbidden", "message": str(pe)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return Response({"error": "Bad Request", "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def work_item_claim_api(request, pk):
    """
    POST /api/items/<id>/claim/
    Atomically claims an unassigned work item.
    Returns 409 Conflict if already claimed.
    """
    qs = get_visible_workitems_queryset(request.user)
    if not qs.filter(pk=pk).exists():
        return Response({"error": "Not Found", "message": "Work item not found."}, status=status.HTTP_404_NOT_FOUND)

    try:
        item = WorkItemService.claim_item(work_item_id=pk, user=request.user)
        serializer = WorkItemDetailSerializer(item, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    except ConflictError as ce:
        return Response(
            {"error": "Conflict", "code": "ALREADY_CLAIMED", "message": str(ce)},
            status=status.HTTP_409_CONFLICT,
        )
    except PermissionDenied as pe:
        return Response({"error": "Forbidden", "message": str(pe)}, status=status.HTTP_403_FORBIDDEN)
    except Exception as e:
        return Response({"error": "Bad Request", "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def work_item_transition_api(request, pk):
    """
    POST /api/items/<id>/transition/
    Transitions workflow state (Open -> In Progress -> Awaiting Approval -> Resolved -> Closed).
    Enforces Lead-only approval.
    """
    qs = get_visible_workitems_queryset(request.user)
    if not qs.filter(pk=pk).exists():
        return Response({"error": "Not Found", "message": "Work item not found."}, status=status.HTTP_404_NOT_FOUND)

    serializer = TransitionActionSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    target_status = serializer.validated_data["target_status"]
    note = serializer.validated_data.get("note")

    try:
        item = WorkItemService.transition_item(
            work_item_id=pk,
            user=request.user,
            target_status=target_status,
            note=note,
        )
        return Response(WorkItemDetailSerializer(item, context={"request": request}).data)
    except ValidationError as ve:
        return Response({"error": "Invalid Transition", "message": str(ve)}, status=status.HTTP_400_BAD_REQUEST)
    except PermissionDenied as pe:
        return Response({"error": "Forbidden", "message": str(pe)}, status=status.HTTP_403_FORBIDDEN)
    except Exception as e:
        return Response({"error": "Bad Request", "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def work_item_activity_api(request, pk):
    """
    GET /api/items/<id>/activity/
    Returns append-only audit event history for the work item.
    """
    qs = get_visible_workitems_queryset(request.user)
    if not qs.filter(pk=pk).exists():
        return Response({"error": "Not Found", "message": "Work item not found."}, status=status.HTTP_404_NOT_FOUND)

    events = (
        ActivityEvent.objects.filter(work_item_id=pk)
        .select_related("actor")
        .order_by("created_at")
    )
    serializer = ActivityEventSerializer(events, many=True)
    return Response(serializer.data)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def work_item_comments_api(request, pk):
    """
    GET /api/items/<id>/comments/
    POST /api/items/<id>/comments/
    """
    qs = get_visible_workitems_queryset(request.user)
    if not qs.filter(pk=pk).exists():
        return Response({"error": "Not Found", "message": "Work item not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        comments = (
            Comment.objects.filter(work_item_id=pk)
            .select_related("author")
            .order_by("created_at")
        )
        serializer = CommentSerializer(comments, many=True)
        return Response(serializer.data)

    elif request.method == "POST":
        content = request.data.get("content", "").strip()
        if not content:
            return Response({"content": ["Comment content cannot be empty."]}, status=status.HTTP_400_BAD_REQUEST)

        try:
            comment = WorkItemService.add_comment(
                work_item_id=pk,
                user=request.user,
                content=content,
            )
            return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)
        except PermissionDenied as pe:
            return Response({"error": "Forbidden", "message": str(pe)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return Response({"error": "Bad Request", "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# TEMPLATE-BASED FRONTEND VIEWS
# ============================================================================

@login_required
def dashboard_view(request):
    """
    Main operations dashboard providing immediate views of:
    1. Assigned to me
    2. Unassigned urgent
    3. Awaiting my approval
    4. Operational summary metrics
    """
    user = request.user
    visible_qs = get_visible_workitems_queryset(user)

    assigned_to_me = visible_qs.filter(
        assignee=user,
        status__in=[WorkItemStatus.OPEN, WorkItemStatus.IN_PROGRESS, WorkItemStatus.AWAITING_APPROVAL]
    ).order_by("-priority", "-created_at")[:10]

    unassigned_urgent = visible_qs.filter(
        assignee__isnull=True,
        priority__in=[WorkItemPriority.HIGH, WorkItemPriority.URGENT],
        status=WorkItemStatus.OPEN,
    ).order_by("-priority", "-created_at")[:10]

    # Find teams where user is Lead or Admin
    lead_team_ids = TeamMembership.objects.filter(
        user=user,
        role__in=[TeamRole.LEAD, TeamRole.ADMIN]
    ).values_list("team_id", flat=True)

    if user.is_superuser:
        awaiting_approval = visible_qs.filter(
            status=WorkItemStatus.AWAITING_APPROVAL
        ).order_by("-priority", "-created_at")[:10]
    else:
        awaiting_approval = visible_qs.filter(
            team_id__in=lead_team_ids,
            status=WorkItemStatus.AWAITING_APPROVAL
        ).order_by("-priority", "-created_at")[:10]

    stats = {
        "total_active": visible_qs.exclude(status=WorkItemStatus.CLOSED).count(),
        "my_open_items": assigned_to_me.count(),
        "unassigned_urgent": unassigned_urgent.count(),
        "awaiting_approval": awaiting_approval.count(),
    }

    context = {
        "stats": stats,
        "assigned_to_me": assigned_to_me,
        "unassigned_urgent": unassigned_urgent,
        "awaiting_approval": awaiting_approval,
    }
    return render(request, "workitems/dashboard.html", context)


@login_required
def work_item_list_view(request):
    """
    Work item list page with search, filters, and pagination.
    """
    visible_qs = get_visible_workitems_queryset(request.user)
    teams = Team.objects.filter(id__in=visible_qs.values_list("team_id", flat=True)).distinct()

    return render(
        request,
        "workitems/item_list.html",
        {
            "teams": teams,
            "statuses": WorkItemStatus.choices,
            "priorities": WorkItemPriority.choices,
            "types": WorkItemType.choices,
        },
    )


@login_required
def work_item_create_view(request):
    """
    Form view to create a new work item.
    """
    user = request.user
    if user.is_superuser:
        teams = Team.objects.all()
    else:
        # User must have Member, Lead, or Admin role to create items in a team
        writable_team_ids = TeamMembership.objects.filter(
            user=user,
            role__in=[TeamRole.MEMBER, TeamRole.LEAD, TeamRole.ADMIN]
        ).values_list("team_id", flat=True)
        teams = Team.objects.filter(id__in=writable_team_ids)

    return render(
        request,
        "workitems/item_form.html",
        {
            "teams": teams,
            "priorities": WorkItemPriority.choices,
            "types": WorkItemType.choices,
            "is_edit": False,
        },
    )


@login_required
def work_item_detail_view(request, pk):
    """
    Detailed work item view with activity timeline, comments, and action controls.
    """
    visible_qs = get_visible_workitems_queryset(request.user)
    try:
        item = visible_qs.get(pk=pk)
    except WorkItem.DoesNotExist:
        raise Http404("Work item not found or you lack permission to view this team's items.")

    user_role = TeamPermissionService.get_user_role(request.user, item.team)
    can_claim = item.assignee is None and TeamPermissionService.can_claim_workitem(request.user, item)
    can_edit = TeamPermissionService.can_update_workitem(request.user, item)

    allowed_transitions = [
        target for target in ALLOWED_TRANSITIONS.get(item.status, [])
        if TeamPermissionService.can_transition_workitem(request.user, item, target)
    ]

    context = {
        "item": item,
        "user_role": user_role,
        "can_claim": can_claim,
        "can_edit": can_edit,
        "allowed_transitions": allowed_transitions,
    }
    return render(request, "workitems/item_detail.html", context)


@login_required
def work_item_edit_view(request, pk):
    """
    Edit work item page with version check and reconciliation.
    """
    visible_qs = get_visible_workitems_queryset(request.user)
    try:
        item = visible_qs.get(pk=pk)
    except WorkItem.DoesNotExist:
        raise Http404("Work item not found.")

    if not TeamPermissionService.can_update_workitem(request.user, item):
        raise PermissionDenied("You do not have permission to edit items in this team.")

    team_members = TeamMembership.objects.filter(team=item.team).select_related("user")

    context = {
        "item": item,
        "team_members": [m.user for m in team_members],
        "priorities": WorkItemPriority.choices,
        "types": WorkItemType.choices,
        "is_edit": True,
    }
    return render(request, "workitems/item_form.html", context)
