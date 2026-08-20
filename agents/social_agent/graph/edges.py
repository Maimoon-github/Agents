"""
social_agent/graph/edges.py
Conditional edge routing functions, quality threshold checks, and HITL decision branches.
Uses imported LangGraph END constant to guarantee deterministic routing.
"""
from typing import Any, Union

try:
    from langgraph.graph import END
except ImportError:
    END = "__end__"

from social_agent.graph.state import SocialAgentState


import logging

logger = logging.getLogger(__name__)

def decide_audit_routing(state: SocialAgentState) -> Union[str, Any]:
    """
    Evaluates LLM Judge results and routes to self-healing, human gate, or direct publication.
    """
    eval_report = state.get("audit_evaluation")
    retry_count = state.get("retry_count", 0)
    hitl_payload = state.get("hitl_payload")
    
    logger.info("[REFLECT & ROUTE] 4. Evaluating composite and safety scores to route execution.")

    # 1. Critical Security / Injection Abort
    if eval_report and not eval_report.is_safe:
        logger.info("                  -> If fatal safety/injection breach => Abort execution immediately.")
        return END

    # 2. Quality Deficit -> Self-Healing (up to 3 retries)
    if eval_report and eval_report.overall_quality_score < 0.90:
        if retry_count < 3:
            logger.info("                  -> If Q < 0.90 and retry_count < 3 => Format remediation directive, route to `act_draft`.")
            return "reflect_remedy"
        # Exhausted retries -> Escalate to Human Gate
        logger.info("                  -> If retry_count >= 3 => Escalate to `hitl_gate` with failure diagnostic report.")
        return "hitl_gate"

    # 3. Mandatory Governance Flag
    if hitl_payload and hitl_payload.required:
        logger.info("                  -> Mandatory governance flag. Routing to hitl_gate.")
        return "hitl_gate"

    # 4. High Quality Clearance -> Dispatch
    if eval_report and eval_report.overall_quality_score >= 0.90 and eval_report.safety_score == 1.0:
        logger.info("                  -> If Q >= 0.90 and S_safety = 1.0 => Route to `publish_dispatch`.")
        return "publish_dispatch"

    return "publish_dispatch"


def decide_hitl_outcome(state: SocialAgentState) -> Union[str, Any]:
    """
    Routes based on human reviewer verdict received from Django Admin.
    """
    hitl_payload = state.get("hitl_payload")
    if hitl_payload and hitl_payload.approved is True:
        return "publish_dispatch"
    return END