"""
social_agent/guardrails/self_healing.py
Error taxonomy classification, bounded exponential backoff retry policy,
remediation feedback injection, and Human-in-the-Loop (HITL) escalation.
"""
import random
import logging
from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError

from .evaluators import AuditEvaluation

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    """Taxonomy of failure modes in the agentic workflow."""
    SYNTAX_SCHEMA_ERROR = "SYNTAX_SCHEMA_ERROR"
    QUALITY_THRESHOLD_FAIL = "QUALITY_THRESHOLD_FAIL"
    RATE_LIMIT_429 = "RATE_LIMIT_429"
    INFRASTRUCTURE_5XX = "INFRASTRUCTURE_5XX"
    FATAL_SECURITY_BREACH = "FATAL_SECURITY_BREACH"


class RemediationAction(str, Enum):
    """Prescribed recovery action for an agent loop."""
    RETRY_WITH_FEEDBACK = "RETRY_WITH_FEEDBACK"
    MODEL_DEGRADATION_FALLBACK = "MODEL_DEGRADATION_FALLBACK"
    ESCALATE_TO_HITL = "ESCALATE_TO_HITL"
    ABORT_CAMPAIGN = "ABORT_CAMPAIGN"


class RemediationDirective(BaseModel):
    """Structured recovery payload returned to graph routing edges."""
    error_category: ErrorCategory = Field(..., description="Classified failure mode.")
    retry_count: int = Field(..., ge=1, le=4, description="Monotonically increasing retry attempt.")
    action: RemediationAction = Field(..., description="Target recovery strategy.")
    feedback_payload: str = Field(..., description="Actionable critique string for agent context.")
    backoff_seconds: float = Field(default=0.0, description="Exponential backoff delay in seconds.")


class SelfHealingManager:
    """
    Coordinates self-healing recovery strategies, computes jittered exponential backoff,
    and enforces hard escalation boundaries (max 3 retries) to prevent infinite loops.
    """
    def __init__(
        self,
        max_retries: int = 3,
        base_backoff_sec: float = 2.0,
        max_backoff_sec: float = 10.0
    ):
        self.max_retries = max_retries
        self.base_backoff_sec = base_backoff_sec
        self.max_backoff_sec = max_backoff_sec

    def classify_failure(
        self,
        eval_report: Optional[AuditEvaluation] = None,
        exception: Optional[Exception] = None
    ) -> ErrorCategory:
        """
        Maps runtime exceptions or quality audit failures into the error taxonomy.
        """
        if exception:
            if isinstance(exception, ValidationError) or "json" in str(exception).lower():
                return ErrorCategory.SYNTAX_SCHEMA_ERROR
            
            exc_str = str(exception).lower()
            if "429" in exc_str or "rate limit" in exc_str:
                return ErrorCategory.RATE_LIMIT_429
            if "injection" in exc_str or "security" in exc_str:
                return ErrorCategory.FATAL_SECURITY_BREACH
            return ErrorCategory.INFRASTRUCTURE_5XX

        if eval_report:
            if not eval_report.is_safe:
                return ErrorCategory.FATAL_SECURITY_BREACH
            if eval_report.overall_quality_score < 0.90:
                return ErrorCategory.QUALITY_THRESHOLD_FAIL

        return ErrorCategory.QUALITY_THRESHOLD_FAIL

    def _calculate_backoff(self, retry_count: int) -> float:
        """
        Computes exponential backoff with uniform random jitter:
        t_backoff = min(max_backoff, base * 2^(retry_count - 1)) + uniform(0, 2)
        """
        exp_delay = self.base_backoff_sec * (2 ** max(0, retry_count - 1))
        bounded = min(self.max_backoff_sec, exp_delay)
        jitter = random.uniform(0.0, 2.0)
        return round(bounded + jitter, 2)

    def format_remediation_prompt(self, eval_report: AuditEvaluation) -> str:
        """
        Generates numbered actionable critique points for injection into drafting prompts.
        """
        critique_lines = [
            f"CRITICAL REMEDIATION FEEDBACK (Composite Quality: {eval_report.overall_quality_score:.2f} < 0.90):"
        ]
        
        idx = 1
        for m in eval_report.metric_scores:
            if not m.passed:
                critique_lines.append(f"{idx}. [{m.dimension.upper()} DEFICIT]: Score {m.score:.2f} < {m.threshold:.2f}. {m.rationale}")
                idx += 1

        for r in eval_report.reasons:
            if not any(r in line for line in critique_lines):
                critique_lines.append(f"{idx}. [VIOLATION]: {r}")
                idx += 1

        critique_lines.append("ACTION REQUIRED: Rewrite the post to strictly adhere to platform character bounds, eliminate all buzzwords, and ground all claims in Brand RAG context.")
        return "\n".join(critique_lines)

    def determine_recovery_action(
        self,
        category: ErrorCategory,
        current_retry_count: int,
        eval_report: Optional[AuditEvaluation] = None,
        custom_feedback: Optional[str] = None
    ) -> RemediationDirective:
        """
        Determines whether to retry with feedback, degrade models, or escalate to human approval.
        """
        next_retry = current_retry_count + 1
        backoff = self._calculate_backoff(next_retry)

        # 1. Fatal Security Breaches -> Immediate Abort
        if category == ErrorCategory.FATAL_SECURITY_BREACH:
            return RemediationDirective(
                error_category=category,
                retry_count=max(1, current_retry_count),
                action=RemediationAction.ABORT_CAMPAIGN,
                feedback_payload="Fatal security violation detected (Prompt Injection or Unredacted PII). Workflow terminated.",
                backoff_seconds=0.0
            )

        # 2. Retry Exhaustion (>= 3 attempts) -> Escalate to HITL Gate
        if current_retry_count >= self.max_retries:
            logger.warning("Self-healing retry threshold reached (%d/%d). Escalating to HITL gate.", current_retry_count, self.max_retries)
            feedback = self.format_remediation_prompt(eval_report) if eval_report else "Automated self-healing retries exhausted."
            return RemediationDirective(
                error_category=category,
                retry_count=current_retry_count,
                action=RemediationAction.ESCALATE_TO_HITL,
                feedback_payload=f"CRITICAL ESCALATION: {feedback}",
                backoff_seconds=0.0
            )

        # 3. Active Self-Healing Cycles (< 3 attempts)
        if category == ErrorCategory.INFRASTRUCTURE_5XX:
            return RemediationDirective(
                error_category=category,
                retry_count=next_retry,
                action=RemediationAction.MODEL_DEGRADATION_FALLBACK,
                feedback_payload="Upstream inference timeout. Retrying with fallback model configuration.",
                backoff_seconds=backoff
            )

        feedback = custom_feedback or (self.format_remediation_prompt(eval_report) if eval_report else "Schema validation failed. Regenerate compliant output.")
        return RemediationDirective(
            error_category=category,
            retry_count=next_retry,
            action=RemediationAction.RETRY_WITH_FEEDBACK,
            feedback_payload=feedback,
            backoff_seconds=backoff
        )

    async def log_remediation_to_audit(
        self,
        campaign_id: str,
        directive: RemediationDirective
    ) -> None:
        """Asynchronously logs the self-healing event into the Django ORM audit trail."""
        try:
            from social_agent.models import AgentAuditLog, SocialCampaign
            campaign = await SocialCampaign.objects.filter(id=campaign_id).afirst()
            if campaign:
                await AgentAuditLog.objects.acreate(
                    campaign=campaign,
                    node_name="self_healing_gate",
                    agent_name="SelfHealingManager",
                    input_state_summary=f"Error Category: {directive.error_category.value} | Attempt: {directive.retry_count}",
                    output_state_summary=f"Prescribed Action: {directive.action.value} | Backoff: {directive.backoff_seconds}s",
                    evaluation_rubric={"feedback": directive.feedback_payload},
                    token_usage={"remediation_tokens": 0},
                    execution_time_seconds=directive.backoff_seconds
                )
        except Exception as e:
            logger.debug("Django ORM logging bypassed in self-healing manager: %s", e)