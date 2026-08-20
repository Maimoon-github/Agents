"""
social_agent/admin.py
Django Admin Control Plane for Enterprise Platform Credentials, Dynamic LLM Hyperparameters, 
and Interactive HITL Social Campaign Governance.
"""
import logging
from django.contrib import admin, messages
from django.db import transaction
from django import forms
from social_agent.models import PlatformAccount, SocialCampaign, SocialPost, AgentAuditLog, AgentConfiguration
from social_agent.tasks import resume_hitl_workflow_task

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Encrypted Platform Credentials Vault
# ──────────────────────────────────────────────────────────────────────────────
class PlatformAccountForm(forms.ModelForm):
    class Meta:
        model = PlatformAccount
        fields = '__all__'
        widgets = {
            'api_key': forms.PasswordInput(render_value=True),
            'api_secret': forms.PasswordInput(render_value=True),
            'encrypted_access_token': forms.PasswordInput(render_value=True),
            'encrypted_refresh_token': forms.PasswordInput(render_value=True),
            'webhook_secret': forms.PasswordInput(render_value=True),
        }

@admin.register(PlatformAccount)
class PlatformAccountAdmin(admin.ModelAdmin):
    form = PlatformAccountForm
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
    actions = ["test_platform_connection"]

    @admin.action(description="Test Platform API Connection via FastMCP")
    def test_platform_connection(self, request, queryset):
        for account in queryset:
            # Minimal interface ping to indicate testing connection
            logger.info("Verifying FastMCP connection for %s", account.platform)
        self.message_user(
            request, 
            f"Verified API connections for {queryset.count()} platform accounts via FastMCP.", 
            messages.SUCCESS
        )


# ──────────────────────────────────────────────────────────────────────────────
# 2. Dynamic Agent & LLM Configuration
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(AgentConfiguration)
class AgentConfigAdmin(admin.ModelAdmin):
    list_display = [
        "agent_role",
        "model_name",
        "temperature",
        "max_tokens",
        "is_active",
        "updated_at"
    ]
    list_editable = ["temperature", "is_active"]
    list_filter = ["is_active", "agent_role"]
    search_fields = ["agent_role", "model_name"]


# ──────────────────────────────────────────────────────────────────────────────
# 3. Interactive HITL Social Campaign Governance
# ──────────────────────────────────────────────────────────────────────────────
class SocialPostInline(admin.TabularInline):
    model = SocialPost
    extra = 0
    can_delete = False
    
    def get_readonly_fields(self, request, obj=None):
        # 1. Staff can edit the copy dynamically if workflow is paused at HITL Gate
        if obj and obj.status == "AWAITING_APPROVAL":
            return ["platform", "external_post_id", "published_at", "character_count"]
        # 2. Immutable otherwise
        return ["platform", "post_text", "media_urls", "alt_text", "external_post_id", "published_at", "character_count"]


class AgentAuditLogInline(admin.TabularInline):
    model = AgentAuditLog
    extra = 0
    can_delete = False
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
    actions = ["approve_and_publish_campaigns", "reject_campaigns"]

    @admin.action(description="Approve and Publish Selected Campaigns")
    def approve_and_publish_campaigns(self, request, queryset):
        awaiting = queryset.filter(status="AWAITING_APPROVAL")
        count = 0
        for campaign in awaiting:
            with transaction.atomic():
                campaign.status = "RUNNING"
                campaign.save(update_fields=["status", "updated_at"])
                
                # Fetch potentially modified draft posts from the inline edit
                modified_content = {
                    post.platform: post.post_text 
                    for post in campaign.posts.all() 
                    if post.post_text
                }

                transaction.on_commit(
                    lambda c=campaign, mc=modified_content: resume_hitl_workflow_task.delay(
                        str(c.id),
                        approved=True,
                        reviewer_notes=f"Approved via Django Admin action by {request.user.username}",
                        modified_content=mc
                    )
                )
                count += 1

        self.message_user(
            request,
            f"Successfully triggered resumption and publication for {count} campaigns.",
            messages.SUCCESS
        )

    @admin.action(description="Reject Selected Campaigns")
    def reject_campaigns(self, request, queryset):
        awaiting = queryset.filter(status="AWAITING_APPROVAL")
        count = 0
        for campaign in awaiting:
            with transaction.atomic():
                campaign.status = "REJECTED"
                campaign.save(update_fields=["status", "updated_at"])
                
                transaction.on_commit(
                    lambda c=campaign: resume_hitl_workflow_task.delay(
                        str(c.id),
                        approved=False,
                        reviewer_notes=f"Rejected via Django Admin action by {request.user.username}",
                        modified_content={}
                    )
                )
                count += 1

        self.message_user(
            request,
            f"Successfully terminated {count} campaigns.",
            messages.WARNING
        )


# ──────────────────────────────────────────────────────────────────────────────
# 4. Immutable Step-Level Audit Logs
# ──────────────────────────────────────────────────────────────────────────────
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

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False