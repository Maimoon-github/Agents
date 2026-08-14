"""
social_agent/graph/workflow.py
Assembles and compiles the LangGraph StateGraph with Postgres checkpointer.
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from social_agent.graph.state import SocialAgentState
from social_agent.graph.nodes import (
    plan_research_node,
    act_draft_node,
    media_prep_node,
    evaluate_audit_node,
    reflect_remedy_node,
    hitl_gate_node,
    publish_dispatch_node
)


def decide_audit_routing(state: SocialAgentState) -> str:
    """
    Conditional edge evaluator for self-healing, human intervention, or direct publication.
    """
    eval_report = state.get("audit_evaluation")
    retry_count = state.get("retry_count", 0)
    
    # 1. Quality threshold failure -> trigger self-healing (up to 3 retries)
    if eval_report and eval_report.overall_quality_score < 0.90:
        if retry_count < 3:
            return "reflect_remedy"
        # Exhausted retries -> escalate to human
        return "hitl_gate"
        
    # 2. Strict human governance flag
    if state["hitl_payload"].required:
        return "hitl_gate"
        
    # 3. High quality & safety passed -> proceed to publish
    return "publish_dispatch"


def decide_hitl_outcome(state: SocialAgentState) -> str:
    """
    Routes based on human reviewer verdict.
    """
    if state["hitl_payload"].approved:
        return "publish_dispatch"
    return END


def create_social_agent_graph():
    """
    Constructs the cyclic state graph topology.
    """
    workflow = StateGraph(SocialAgentState)
    
    # Add Nodes
    workflow.add_node("plan_research", plan_research_node)
    workflow.add_node("act_draft", act_draft_node)
    workflow.add_node("media_prep", media_prep_node)
    workflow.add_node("evaluate_audit", evaluate_audit_node)
    workflow.add_node("reflect_remedy", reflect_remedy_node)
    workflow.add_node("hitl_gate", hitl_gate_node)
    workflow.add_node("publish_dispatch", publish_dispatch_node)
    
    # Add Edges
    workflow.add_edge(START, "plan_research")
    workflow.add_edge("plan_research", "act_draft")
    workflow.add_edge("act_draft", "media_prep")
    workflow.add_edge("media_prep", "evaluate_audit")
    
    # Dynamic Self-Healing & Governance Routing
    workflow.add_conditional_edges(
        "evaluate_audit",
        decide_audit_routing,
        {
            "reflect_remedy": "reflect_remedy",
            "hitl_gate": "hitl_gate",
            "publish_dispatch": "publish_dispatch"
        }
    )
    
    workflow.add_edge("reflect_remedy", "act_draft")
    
    workflow.add_conditional_edges(
        "hitl_gate",
        decide_hitl_outcome,
        {
            "publish_dispatch": "publish_dispatch",
            END: END
        }
    )
    
    workflow.add_edge("publish_dispatch", END)
    
    return workflow