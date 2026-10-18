from rest_framework import serializers
from accounts.models import User
from teams.models import Team
from teams.permissions import TeamPermissionService
from .models import (
    WorkItem,
    WorkItemType,
    WorkItemPriority,
    WorkItemStatus,
    Comment,
    ActivityEvent,
    OutboxMessage,
)
from .services import ALLOWED_TRANSITIONS


class UserSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "full_name", "email", "job_title"]


class TeamSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ["id", "name", "slug", "is_restricted"]


class CommentSerializer(serializers.ModelSerializer):
    author = UserSummarySerializer(read_only=True)

    class Meta:
        model = Comment
        fields = ["id", "work_item", "author", "content", "created_at"]
        read_only_fields = ["id", "work_item", "author", "created_at"]


class ActivityEventSerializer(serializers.ModelSerializer):
    actor = UserSummarySerializer(read_only=True)

    class Meta:
        model = ActivityEvent
        fields = ["id", "work_item", "actor", "event_type", "message", "from_state", "to_state", "created_at"]
        read_only_fields = fields


class WorkItemListSerializer(serializers.ModelSerializer):
    team = TeamSummarySerializer(read_only=True)
    assignee = UserSummarySerializer(read_only=True)
    creator = UserSummarySerializer(read_only=True)

    class Meta:
        model = WorkItem
        fields = [
            "id",
            "title",
            "type",
            "priority",
            "status",
            "team",
            "assignee",
            "creator",
            "due_date",
            "version",
            "created_at",
            "updated_at",
        ]


class WorkItemDetailSerializer(serializers.ModelSerializer):
    team = TeamSummarySerializer(read_only=True)
    assignee = UserSummarySerializer(read_only=True)
    creator = UserSummarySerializer(read_only=True)
    comments = CommentSerializer(many=True, read_only=True)
    activity_events = ActivityEventSerializer(many=True, read_only=True)
    allowed_transitions = serializers.SerializerMethodField()
    can_claim = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = WorkItem
        fields = [
            "id",
            "title",
            "description",
            "type",
            "priority",
            "status",
            "team",
            "assignee",
            "creator",
            "due_date",
            "version",
            "created_at",
            "updated_at",
            "comments",
            "activity_events",
            "allowed_transitions",
            "can_claim",
            "can_edit",
        ]

    def get_allowed_transitions(self, obj):
        request = self.context.get("request")
        user = request.user if request else None
        all_allowed = ALLOWED_TRANSITIONS.get(obj.status, [])
        if not user or not user.is_authenticated:
            return []
        # Filter by user's permission for each transition
        return [
            target for target in all_allowed
            if TeamPermissionService.can_transition_workitem(user, obj, target)
        ]

    def get_can_claim(self, obj):
        request = self.context.get("request")
        user = request.user if request else None
        if not user or not user.is_authenticated or obj.assignee is not None:
            return False
        return TeamPermissionService.can_claim_workitem(user, obj)

    def get_can_edit(self, obj):
        request = self.context.get("request")
        user = request.user if request else None
        if not user or not user.is_authenticated:
            return False
        return TeamPermissionService.can_update_workitem(user, obj)


class WorkItemCreateSerializer(serializers.ModelSerializer):
    team_id = serializers.PrimaryKeyRelatedField(
        queryset=Team.objects.all(), source="team", write_only=True, required=False
    )
    team = serializers.PrimaryKeyRelatedField(
        queryset=Team.objects.all(), write_only=True, required=False
    )
    assignee_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source="assignee", write_only=True, required=False, allow_null=True
    )
    assignee = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = WorkItem
        fields = [
            "id",
            "title",
            "description",
            "type",
            "priority",
            "team",
            "team_id",
            "assignee",
            "assignee_id",
            "due_date",
        ]

    def validate(self, attrs):
        if "team" not in attrs:
            raise serializers.ValidationError({"team": "This field is required."})
        return attrs

    def validate_title(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("Title cannot be empty.")
        return val


class WorkItemUpdateSerializer(serializers.ModelSerializer):
    version = serializers.IntegerField(required=False, help_text="Precondition version for optimistic locking.")
    assignee_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source="assignee", write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = WorkItem
        fields = [
            "title",
            "description",
            "type",
            "priority",
            "assignee_id",
            "due_date",
            "version",
        ]


class TransitionActionSerializer(serializers.Serializer):
    target_status = serializers.ChoiceField(choices=WorkItemStatus.choices)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ClaimActionSerializer(serializers.Serializer):
    pass
