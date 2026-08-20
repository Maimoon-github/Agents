"""
social_agent/graph/__init__.py
Unified exports for the LangGraph state machine: nodes, edges, checkpointer, and workflow runners.
All names here match the actual function signatures in their respective modules.
"""
from .state import (
    SocialAgentState,
    PlatformPostPayload,
    AuditEvaluation,
    HITLApprovalPayload,
)
from .checkpointer import get_postgres_checkpointer
from .nodes import (
    plan_research_node,
    act_research_and_draft_node,   # Canonical name — was incorrectly aliased in prior __init__
    media_prep_node,
    evaluate_audit_node,
    reflect_remedy_node,
    hitl_gate_node,
    publish_dispatch_node,
)
from .edges import (
    decide_audit_routing,
    decide_hitl_outcome,
)
from .workflow import (
    create_social_agent_graph,
    run_workflow_stream,
    resume_workflow_stream,
)

__all__ = [
    "SocialAgentState",
    "PlatformPostPayload",
    "AuditEvaluation",
    "HITLApprovalPayload",
    "get_postgres_checkpointer",
    "plan_research_node",
    "act_research_and_draft_node",
    "media_prep_node",
    "evaluate_audit_node",
    "reflect_remedy_node",
    "hitl_gate_node",
    "publish_dispatch_node",
    "decide_audit_routing",
    "decide_hitl_outcome",
    "create_social_agent_graph",
    "run_workflow_stream",
    "resume_workflow_stream",
]