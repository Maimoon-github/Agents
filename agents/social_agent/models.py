"""
social_agent/models.py
Enterprise Django models for persistence, auditability, OAuth token isolation, and HITL state.
"""
import uuid
from django.db import models
from django.utils import timezone


class PlatformAccount(models.Model):
    """
    Stores platform-specific credentials, encrypted tokens, and rate-limit counters.
    """
    PLATFORM_CHOICES = [
        ("x_twitter", "X (Twitter)"),
        ("instagram", "Instagram"),
        ("tiktok", "TikTok"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    platform = models.CharField(max_length=32, choices=PLATFORM_CHOICES)
    account_handle = models.CharField(max_length=128)
    encrypted_access_token = models.TextField(help_text="Encrypted OAuth2 Bearer Token")
    encrypted_refresh_token = models.TextField(blank=True, null=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    rate_limit_remaining = models.IntegerField(default=100)
    rate_limit_reset_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("platform", "account_handle")
        indexes = [models.Index(fields=["platform", "account_handle"])]
        verbose_name = "Platform Account"
        verbose_name_plural = "Platform Accounts"

    def __str__(self):
        return f"{self.get_platform_display()} - @{self.account_handle}"


class SocialCampaign(models.Model):
    """
    Tracks campaign lifecycles, LangGraph thread isolation, composite quality scores, and HITL state.
    """
    STATUS_CHOICES = [
        ("PENDING", "Pending Execution"),
        ("RUNNING", "Running In Graph"),
        ("AWAITING_APPROVAL", "Awaiting Human Approval (HITL)"),
        ("APPROVED", "Approved by Human"),
        ("REJECTED", "Rejected by Human"),
        ("PUBLISHED", "Published to Platforms"),
        ("FAILED", "Failed / Fatal Error"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    raw_prompt = models.TextField(help_text="Original campaign objective or prompt")
    target_platforms = models.JSONField(
        default=list,
        help_text="List of platforms: ['x_twitter', 'instagram', 'tiktok']"
    )
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="PENDING")
    
    # LangGraph Thread Isolation & Checkpoint References
    langgraph_thread_id = models.CharField(max_length=128, unique=True, db_index=True)
    current_checkpoint_id = models.CharField(max_length=128, blank=True, null=True)
    
    # Quantitative Quality and Safety Evaluation Metrics
    overall_quality_score = models.FloatField(default=0.0)
    safety_passed = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Social Campaign"
        verbose_name_plural = "Social Campaigns"

    def __str__(self):
        return f"{self.title} [{self.status}]"


class SocialPost(models.Model):
    """
    Represents generated and published platform-specific content items.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(
        SocialCampaign,
        on_delete=models.CASCADE,
        related_name="posts"
    )
    platform = models.CharField(max_length=32)
    post_text = models.TextField()
    media_urls = models.JSONField(default=list, blank=True)
    alt_text = models.TextField(blank=True, null=True)
    external_post_id = models.CharField(max_length=128, blank=True, null=True)
    published_at = models.DateTimeField(null=True, blank=True)
    character_count = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Social Post"
        verbose_name_plural = "Social Posts"

    def __str__(self):
        return f"{self.platform} Post for {self.campaign.title}"


class AgentAuditLog(models.Model):
    """
    Immutable step-level audit trail capturing node execution traces, token usage, and evaluation scores.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(
        SocialCampaign,
        on_delete=models.CASCADE,
        related_name="audit_logs"
    )
    node_name = models.CharField(max_length=64)
    agent_name = models.CharField(max_length=64)
    input_state_summary = models.TextField()
    output_state_summary = models.TextField()
    evaluation_rubric = models.JSONField(default=dict, blank=True)
    execution_time_seconds = models.FloatField(default=0.0)
    token_usage = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Agent Audit Log"
        verbose_name_plural = "Agent Audit Logs"

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {self.node_name} ({self.campaign.title})"