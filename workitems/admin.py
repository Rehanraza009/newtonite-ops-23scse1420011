from django.contrib import admin
from .models import (
    WorkItem,
    Comment,
    ActivityEvent,
    IdempotencyRecord,
    OutboxMessage,
)


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    readonly_fields = ["author", "content", "created_at"]


class ActivityEventInline(admin.TabularInline):
    model = ActivityEvent
    extra = 0
    readonly_fields = ["actor", "event_type", "message", "from_state", "to_state", "created_at"]


@admin.register(WorkItem)
class WorkItemAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "type", "priority", "status", "team", "assignee", "version", "created_at")
    list_filter = ("status", "priority", "type", "team")
    search_fields = ("title", "description")
    readonly_fields = ("version", "created_at", "updated_at")
    inlines = [CommentInline, ActivityEventInline]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("id", "work_item", "author", "created_at")
    search_fields = ("content",)


@admin.register(ActivityEvent)
class ActivityEventAdmin(admin.ModelAdmin):
    list_display = ("id", "work_item", "actor", "event_type", "created_at")
    list_filter = ("event_type",)
    readonly_fields = ("work_item", "actor", "event_type", "message", "from_state", "to_state", "created_at")


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):
    list_display = ("key", "user", "response_status", "created_at")
    readonly_fields = ("key", "user", "request_hash", "response_status", "response_body", "created_at")


@admin.register(OutboxMessage)
class OutboxMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "topic", "status", "attempts", "created_at", "processed_at")
    list_filter = ("status", "topic")
    readonly_fields = ("id", "topic", "payload", "created_at")
