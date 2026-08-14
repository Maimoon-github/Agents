"""
social_agent/graph/state.py
Typed state definition for LangGraph cyclic execution with Pydantic schemas and channel reducers.
"""
import operator
from typing import Annotated, Dict, List, Optional, Any, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, Field


class PlatformPostPayload(BaseModel):
    """Payload schema for an individual platform post draft."""
    platform: Literal["x_twitter", "instagram", "tiktok"] = Field(..., description="Target platform identifier.")
    content: str = Field(..., description="The copy text for the post.")
    hashtags: List[str] = Field(default_factory=list, description="Extracted hashtags.")
    media_urls: List[str] = Field(default_factory=list, description="Public HTTPS CDN links.")
    alt_text: Optional[str] = Field(default=None, description="Accessibility alt text description.")
    character_count: int = Field(default=0, description="String length of post copy.")
    estimated_reading_time_sec: int = Field(default=0, description="Estimated reading duration.")


class AuditEvaluation(BaseModel):
    """Evaluation scoring and compliance report for campaign drafts."""
    post_id: str = Field(default="draft_1", description="Identifier of the evaluated draft.")
    platform: Optional[str] = Field(default=None, description="Platform evaluated.")
    faithfulness_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Groundedness against Brand RAG.")
    brand_voice_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Tone alignment score.")
    formatting_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Length & hashtag compliance.")
    safety_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Policy & PII cleanliness.")
    overall_quality_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Composite quality metric Q.")
    is_safe: bool = Field(default=True, description="Zero-tolerance safety status.")
    reasons: List[str] = Field(default_factory=list, description="List of violations or feedback rationales.")
    remediation_suggestions: Optional[str] = Field(default=None, description="Actionable critique for drafting.")


class HITLApprovalPayload(BaseModel):
    """Human-in-the-loop state and review response schema."""
    required: bool = Field(default=False, description="Whether human authorization is enforced.")
    approved: Optional[bool] = Field(default=None, description="Human verdict upon resumption.")
    reviewer_notes: Optional[str] = Field(default=None, description="Operator feedback or review notes.")
    modified_content: Optional[Dict[str, str]] = Field(default=None, description="Map of platform to manually edited text.")


class SocialAgentState(TypedDict, total=False):
    """
    Central state container for the social media agent workflow.
    Reducers:
      - error_logs and execution_history use operator.add for immutable append-only tracking.
      - retry_count, draft_posts, and audit_evaluation are overwritten per node turn.
    """
    # Campaign Metadata
    campaign_id: str
    thread_id: str
    original_prompt: str
    target_platforms: List[str]

    # Cognitive Reasoning Stack
    research_context: List[str]
    query_rewrite_count: int
    draft_posts: Dict[str, PlatformPostPayload]

    # Quality & Self-Healing
    audit_evaluation: Optional[AuditEvaluation]
    retry_count: int
    remediation_feedback: Optional[str]

    # Governance & Execution
    hitl_payload: HITLApprovalPayload
    published_post_ids: Dict[str, str]

    # Immutably Appended Audit Reducers
    error_logs: Annotated[List[str], operator.add]
    execution_history: Annotated[List[str], operator.add]