"""
social_agent/admin.py
Django Admin dashboard with inline audit trails and staff HITL approval/rejection controls.
"""
from django.contrib import admin, messages
from django.db import transaction
from social_agent.models import PlatformAccount, SocialCampaign, SocialPost, AgentAuditLog
from social_agent.tasks import resume_hitl_workflow_task


class SocialPostInline(admin.TabularInline):
    model = SocialPost
    extra = 0
    readonly_fields = [
        "platform",
        "post_text",
        "media_urls",
        "alt_text",
        "external_post_id",
        "published_at",
        "character_count"
    ]
    can_delete = False


class AgentAuditLogInline(admin.TabularInline):
    model = AgentAuditLog
    extra = 0
    readonly_fields = [
        "timestamp",
        "node_name",
        "agent_name",
        "input_state_summary",
        "output_state_summary",
        "evaluation_rubric",
        "execution_time_seconds",
        "token_usage"
    ]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SocialCampaign)
class SocialCampaignAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "status",
        "overall_quality_score",
        "safety_passed",
        "created_at",
        "langgraph_thread_id"
    ]
    list_filter = ["status", "safety_passed", "created_at"]
    search_fields = ["title", "raw_prompt", "langgraph_thread_id"]
    readonly_fields = [
        "id",
        "langgraph_thread_id",
        "current_checkpoint_id",
        "overall_quality_score",
        "safety_passed",
        "created_at",
        "updated_at"
    ]
    inlines = [SocialPostInline, AgentAuditLogInline]
    actions = ["approve_selected_campaigns", "reject_selected_campaigns"]

    @admin.action(description="Approve and Publish Selected Campaigns (HITL Gate)")
    def approve_selected_campaigns(self, request, queryset):
        awaiting = queryset.filter(status="AWAITING_APPROVAL")
        count = 0
        for campaign in awaiting:
            with transaction.atomic():
                campaign.status = "RUNNING"
                campaign.save(update_fields=["status", "updated_at"])
                transaction.on_commit(
                    lambda c=campaign: resume_hitl_workflow_task.delay(
                        str(c.id),
                        True,
                        f"Approved via Django Admin action by {request.user.username}",
                        {}
                    )
                )
                count += 1

        self.message_user(
            request,
            f"Successfully triggered resumption and publication for {count} campaigns.",
            messages.SUCCESS
        )

    @admin.action(description="Reject Selected Campaigns (HITL Gate)")
    def reject_selected_campaigns(self, request, queryset):
        awaiting = queryset.filter(status="AWAITING_APPROVAL")
        count = 0
        for campaign in awaiting:
            with transaction.atomic():
                campaign.status = "REJECTED"
                campaign.save(update_fields=["status", "updated_at"])
                transaction.on_commit(
                    lambda c=campaign: resume_hitl_workflow_task.delay(
                        str(c.id),
                        False,
                        f"Rejected via Django Admin action by {request.user.username}",
                        {}
                    )
                )
                count += 1

        self.message_user(
            request,
            f"Successfully terminated {count} campaigns.",
            messages.WARNING
        )


@admin.register(PlatformAccount)
class PlatformAccountAdmin(admin.ModelAdmin):
    list_display = [
        "platform",
        "account_handle",
        "is_active",
        "rate_limit_remaining",
        "token_expires_at",
        "created_at"
    ]
    list_filter = ["platform", "is_active"]
    search_fields = ["account_handle"]
    readonly_fields = ["created_at"]


@admin.register(AgentAuditLog)
class AgentAuditLogAdmin(admin.ModelAdmin):
    list_display = [
        "timestamp",
        "campaign",
        "node_name",
        "agent_name",
        "execution_time_seconds"
    ]
    list_filter = ["node_name", "agent_name", "timestamp"]
    search_fields = ["campaign__title", "node_name", "input_state_summary"]
    readonly_fields = [
        "id",
        "campaign",
        "node_name",
        "agent_name",
        "input_state_summary",
        "output_state_summary",
        "evaluation_rubric",
        "execution_time_seconds",
        "token_usage",
        "timestamp"
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False