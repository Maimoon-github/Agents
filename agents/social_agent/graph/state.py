"""
social_agent/graph/state.py
Typed state definition for LangGraph cyclic execution with Pydantic schemas.
"""
from typing import Annotated, Dict, List, Optional, Any, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
import operator


class PlatformPostPayload(BaseModel):
    platform: Literal["x_twitter", "instagram", "tiktok"]
    content: str = Field(..., description="The copy text for the post")
    hashtags: List[str] = Field(default_factory=list)
    media_urls: List[str] = Field(default_factory=list)
    alt_text: Optional[str] = None
    character_count: int = 0
    estimated_reading_time_sec: int = 0


class AuditEvaluation(BaseModel):
    faithfulness_score: float = Field(..., ge=0.0, le=1.0)
    brand_voice_score: float = Field(..., ge=0.0, le=1.0)
    safety_score: float = Field(..., ge=0.0, le=1.0)
    overall_quality_score: float = Field(..., ge=0.0, le=1.0)
    is_safe: bool = True
    reasons: List[str] = Field(default_factory=list)
    remediation_suggestions: Optional[str] = None


class HITLApprovalPayload(BaseModel):
    required: bool = False
    approved: Optional[bool] = None
    reviewer_notes: Optional[str] = None
    modified_payloads: Optional[Dict[str, PlatformPostPayload]] = None


class SocialAgentState(TypedDict):
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
    
    # Audit Trail & Error Handling
    error_logs: Annotated[List[str], operator.add]
    execution_history: Annotated[List[str], operator.add]