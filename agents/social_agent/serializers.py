"""
social_agent/serializers.py
Django REST Framework serializers with explicit field definitions and input validation.
"""
from rest_framework import serializers
from social_agent.models import PlatformAccount, SocialCampaign, SocialPost, AgentAuditLog


class PlatformAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformAccount
        fields = [
            "id",
            "platform",
            "account_handle",
            "is_active",
            "rate_limit_remaining",
            "token_expires_at",
            "created_at"
        ]
        read_only_fields = ["id", "created_at"]


class SocialPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialPost
        fields = [
            "id",
            "platform",
            "post_text",
            "media_urls",
            "alt_text",
            "external_post_id",
            "published_at",
            "character_count"
        ]
        read_only_fields = ["id", "published_at"]


class AgentAuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentAuditLog
        fields = [
            "id",
            "node_name",
            "agent_name",
            "input_state_summary",
            "output_state_summary",
            "evaluation_rubric",
            "execution_time_seconds",
            "token_usage",
            "timestamp"
        ]
        read_only_fields = ["id", "timestamp"]


class CampaignCreateSerializer(serializers.Serializer):
    """Input validation for triggering a new multi-agent campaign."""
    prompt = serializers.CharField(min_length=5, required=True, help_text="Campaign objective or creative brief.")
    platforms = serializers.ListField(
        child=serializers.ChoiceField(choices=["x_twitter", "instagram", "tiktok"]),
        default=["x_twitter", "instagram"],
        required=False,
        help_text="Target social platforms."
    )
    title = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    def validate_platforms(self, value):
        if not value:
            raise serializers.ValidationError("At least one target platform must be selected.")
        return value


class HITLApprovalSerializer(serializers.Serializer):
    """Input schema for human reviewer decisions and manual copy overrides."""
    approved = serializers.BooleanField(required=True, help_text="True to publish, False to abort/reject.")
    notes = serializers.CharField(required=False, allow_blank=True, default="", help_text="Reviewer audit notes.")
    modified_content = serializers.DictField(
        child=serializers.CharField(),
        required=False,
        default=dict,
        help_text="Map of platform names to revised post copy."
    )


class CampaignDetailSerializer(serializers.ModelSerializer):
    """Comprehensive nested representation of campaign state, posts, and audit traces."""
    posts = SocialPostSerializer(many=True, read_only=True)
    audit_logs = AgentAuditLogSerializer(many=True, read_only=True)

    class Meta:
        model = SocialCampaign
        fields = [
            "id",
            "title",
            "raw_prompt",
            "target_platforms",
            "status",
            "langgraph_thread_id",
            "current_checkpoint_id",
            "overall_quality_score",
            "safety_passed",
            "created_at",
            "updated_at",
            "posts",
            "audit_logs"
        ]
        read_only_fields = fields