"""
social_agent/agents/auditor.py
LLM-as-a-Judge and Compliance Auditor Agent enforcing safety, faithfulness, and brand quality gates.
"""
import logging
from typing import Dict, Any, List, Optional

from social_agent.graph.state import PlatformPostPayload, AuditEvaluation
from social_agent.guardrails.evaluators import LLMJudgeEvaluator
from social_agent.guardrails.safety import SafetyGuardrail

logger = logging.getLogger(__name__)


class ComplianceAuditorAgent:
    """
    Evaluates generated drafts against Brand RAG ground truth, platform formatting constraints,
    and safety policies, providing actionable remediation feedback when quality falls below Q < 0.90.
    """
    def __init__(
        self,
        evaluator: Optional[LLMJudgeEvaluator] = None,
        safety: Optional[SafetyGuardrail] = None
    ):
        self.evaluator = evaluator or LLMJudgeEvaluator()
        self.safety = safety or SafetyGuardrail()

    async def audit_campaign_drafts(
        self,
        drafts: Dict[str, PlatformPostPayload],
        context: List[str]
    ) -> AuditEvaluation:
        """
        Executes dual-pass evaluation:
        1. Deterministic safety, PII, and buzzword scan.
        2. LLM-as-a-Judge multi-metric scoring (Faithfulness, Brand Tone, Formatting, Safety).

        Args:
            drafts: Map of platform names to PlatformPostPayload drafts.
            context: Brand guidelines and research context chunks.

        Returns:
            Composite AuditEvaluation report.
        """
        logger.info("ComplianceAuditorAgent: Starting audit across %d drafts", len(drafts))

        # 1. Batch LLM-as-a-Judge Evaluation
        eval_map = await self.evaluator.batch_evaluate(drafts, context)

        # 2. Outbound Safety & PII Verification
        worst_eval: Optional[AuditEvaluation] = None
        all_reasons: List[str] = []
        is_overall_safe = True

        for platform, post in drafts.items():
            safety_res = await self.safety.validate_outbound_content(post.content, platform)
            if not safety_res.is_safe:
                is_overall_safe = False
                all_reasons.extend(safety_res.detected_violations)

            platform_eval = eval_map.get(platform)
            if platform_eval:
                all_reasons.extend(platform_eval.reasons)
                if worst_eval is None or platform_eval.overall_quality_score < worst_eval.overall_quality_score:
                    worst_eval = platform_eval

        if worst_eval is None:
            worst_eval = AuditEvaluation(
                platform="composite",
                overall_quality_score=1.0,
                is_safe=is_overall_safe,
                reasons=all_reasons
            )

        worst_eval.is_safe = is_overall_safe
        worst_eval.reasons = list(set(all_reasons))

        # Deduplicate and formulate remediation feedback if score is below passing gate (0.90)
        if worst_eval.overall_quality_score < 0.90 or not is_overall_safe:
            critique = "Resolve the following audit failures: " + "; ".join(worst_eval.reasons)
            worst_eval.remediation_suggestions = critique

        logger.info(
            "ComplianceAuditorAgent: Audit completed. Overall Quality Q = %.3f | Is Safe = %s",
            worst_eval.overall_quality_score, worst_eval.is_safe
        )
        return worst_eval