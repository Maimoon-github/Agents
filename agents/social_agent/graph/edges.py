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


def decide_audit_routing(state: SocialAgentState) -> Union[str, Any]:
    """
    Evaluates LLM Judge results and routes to self-healing, human gate, or direct publication.

    Conditions:
      1. is_safe is False -> Immediate Abort (END).
      2. overall_quality_score < 0.90 and retry_count < 3 -> reflect_remedy.
      3. overall_quality_score < 0.90 and retry_count >= 3 -> hitl_gate.
      4. hitl_payload.required is True -> hitl_gate.
      5. overall_quality_score >= 0.90 and is_safe is True -> publish_dispatch.
    """
    eval_report = state.get("audit_evaluation")
    retry_count = state.get("retry_count", 0)
    hitl_payload = state.get("hitl_payload")

    # 1. Critical Security / Injection Abort
    if eval_report and not eval_report.is_safe:
        return END

    # 2. Quality Deficit -> Self-Healing (up to 3 retries)
    if eval_report and eval_report.overall_quality_score < 0.90:
        if retry_count < 3:
            return "reflect_remedy"
        # Exhausted retries -> Escalate to Human Gate
        return "hitl_gate"

    # 3. Mandatory Governance Flag
    if hitl_payload and hitl_payload.required:
        return "hitl_gate"

    # 4. High Quality Clearance -> Dispatch
    if eval_report and eval_report.overall_quality_score >= 0.90:
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