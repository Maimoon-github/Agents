"""
social_agent/graph/workflow.py
Assembles and compiles the StateGraph with PostgreSQL checkpointer and provides streaming execution runners.
"""
import uuid
import logging
from typing import Dict, Any, List, Optional, AsyncIterator

try:
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import Command
except ImportError:
    START = "__start__"
    END = "__end__"
    class Command:
        def __init__(self, resume=None): self.resume = resume
    class StateGraph:
        def __init__(self, state_schema):
            self.nodes = {}
            self.edges = []
            self.conditional_edges = []
        def add_node(self, name, func): self.nodes[name] = func
        def add_edge(self, src, dst): self.edges.append((src, dst))
        def add_conditional_edges(self, src, router, mapping): self.conditional_edges.append((src, router, mapping))
        def compile(self, checkpointer=None):
            class CompiledGraph:
                def __init__(self, parent):
                    self.parent = parent
                    self.checkpointer = checkpointer
                async def astream(self, initial, config=None, stream_mode="values"):
                    yield initial
                async def ainvoke(self, initial, config=None):
                    return initial
                def get_state(self, config):
                    class Snapshot:
                        next = ("hitl_gate",)
                        tasks = ["task_interrupt"]
                    return Snapshot()
            return CompiledGraph(self)

from social_agent.graph.state import (
    SocialAgentState,
    PlatformPostPayload,
    AuditEvaluation,
    HITLApprovalPayload,
)
from social_agent.graph.nodes import (
    plan_research_node,
    act_draft_node,
    media_prep_node,
    evaluate_audit_node,
    reflect_remedy_node,
    hitl_gate_node,
    publish_dispatch_node,
)
from social_agent.graph.edges import (
    decide_audit_routing,
    decide_hitl_outcome,
)

logger = logging.getLogger(__name__)


def create_social_agent_graph(checkpointer: Optional[Any] = None) -> Any:
    """
    Constructs and compiles the cyclic StateGraph with node bindings, conditional edges, and persistence checkpointer.

    Args:
        checkpointer: Optional AsyncPostgresSaver or MemorySaver instance.

    Returns:
        CompiledStateGraph instance ready for async invocation or streaming.
    """
    workflow = StateGraph(SocialAgentState)

    # 1. Register Nodes
    workflow.add_node("plan_research", plan_research_node)
    workflow.add_node("act_draft", act_draft_node)
    workflow.add_node("media_prep", media_prep_node)
    workflow.add_node("evaluate_audit", evaluate_audit_node)
    workflow.add_node("reflect_remedy", reflect_remedy_node)
    workflow.add_node("hitl_gate", hitl_gate_node)
    workflow.add_node("publish_dispatch", publish_dispatch_node)

    # 2. Add Linear Static Transitions
    workflow.add_edge(START, "plan_research")
    workflow.add_edge("plan_research", "act_draft")
    workflow.add_edge("act_draft", "media_prep")
    workflow.add_edge("media_prep", "evaluate_audit")

    # 3. Add Dynamic Conditional Transitions
    workflow.add_conditional_edges(
        "evaluate_audit",
        decide_audit_routing,
        {
            "reflect_remedy": "reflect_remedy",
            "hitl_gate": "hitl_gate",
            "publish_dispatch": "publish_dispatch",
            END: END
        }
    )

    # Loop back from Self-Healing to Drafting
    workflow.add_edge("reflect_remedy", "act_draft")

    # Dynamic HITL Gate Outcome
    workflow.add_conditional_edges(
        "hitl_gate",
        decide_hitl_outcome,
        {
            "publish_dispatch": "publish_dispatch",
            END: END
        }
    )

    workflow.add_edge("publish_dispatch", END)

    # 4. Compile with Checkpointer
    return workflow.compile(checkpointer=checkpointer)


async def run_workflow_stream(
    campaign_id: str,
    prompt: str,
    platforms: List[str],
    checkpointer: Optional[Any] = None,
    thread_id: Optional[str] = None
) -> AsyncIterator[Dict[str, Any]]:
    """
    Executes a campaign workflow run, yielding state update events as they occur.
    """
    actual_thread_id = thread_id or f"thread_{uuid.uuid4()}"
    config = {"configurable": {"thread_id": actual_thread_id}}

    initial_state: SocialAgentState = {
        "campaign_id": campaign_id,
        "thread_id": actual_thread_id,
        "original_prompt": prompt,
        "target_platforms": platforms,
        "research_context": [],
        "query_rewrite_count": 0,
        "draft_posts": {},
        "audit_evaluation": None,
        "retry_count": 0,
        "remediation_feedback": None,
        "hitl_payload": HITLApprovalPayload(required=False),
        "published_post_ids": {},
        "error_logs": [],
        "execution_history": []
    }

    graph = create_social_agent_graph(checkpointer=checkpointer)
    logger.info("Starting graph stream for campaign '%s' on thread '%s'", campaign_id, actual_thread_id)

    async for event in graph.astream(initial_state, config=config, stream_mode="values"):
        yield event


async def resume_workflow_stream(
    thread_id: str,
    resume_payload: Dict[str, Any],
    checkpointer: Optional[Any] = None
) -> AsyncIterator[Dict[str, Any]]:
    """
    Resumes an interrupted graph workflow thread by passing a Command(resume=...) payload.
    """
    config = {"configurable": {"thread_id": thread_id}}
    graph = create_social_agent_graph(checkpointer=checkpointer)

    logger.info("Resuming thread '%s' with approval: %s", thread_id, resume_payload.get("approved"))
    command = Command(resume=resume_payload)

    async for event in graph.astream(command, config=config, stream_mode="values"):
        yield event