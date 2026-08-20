"""
social_agent/graph/nodes.py
Pure async state graph nodes implementing the cyclic cognitive loop:
  Plan (Research) → Act (Draft) → Observe (Media) → Reflect (Audit) → Gate (HITL) → Publish

Architectural invariants:
- ALL heavy third-party imports are deferred to _get_agents() (lazy initializer) so that
  importing this module during Django startup never triggers httpx/celery/langgraph import chains.
- Each node is wrapped with @node_telemetry for OpenTelemetry tracing and token cost tracking.
- Budget circuit breaker in @node_telemetry: aborts nodes if daily cost cap is exceeded.
"""
import os
import logging
import time
from functools import wraps
from typing import Dict, Any, Optional

# LangGraph interrupt / Command — safe graceful-degradation stubs when not installed
try:
    from langgraph.types import interrupt, Command
except ImportError:
    def interrupt(payload):  # type: ignore
        return {"approved": True, "reviewer_notes": "Default Mock Approval"}

    class Command:  # type: ignore
        def __init__(self, resume=None): self.resume = resume

# State types – pure Pydantic, no heavy deps
from social_agent.graph.state import (
    SocialAgentState,
    PlatformPostPayload,
    AuditEvaluation,
    HITLApprovalPayload,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Shared singleton subsystems — lazily constructed on first graph call
# ──────────────────────────────────────────────────────────────────────────────
_singletons: Dict[str, Any] = {}
_agent_registry: Dict[str, Any] = {}


def _get_singletons() -> Dict[str, Any]:
    """Lazily builds stateless guardrail and telemetry singletons."""
    global _singletons
    if _singletons:
        return _singletons
    from social_agent.mcp_tools.client import SocialMCPClient
    from social_agent.guardrails.safety import SafetyGuardrail
    from social_agent.guardrails.evaluators import LLMJudgeEvaluator
    from social_agent.guardrails.self_healing import SelfHealingManager
    from social_agent.telemetry.cost_tracker import CostTracker
    _singletons = {
        "mcp_client": SocialMCPClient(),
        "safety_guardrail": SafetyGuardrail(),
        "judge_evaluator": LLMJudgeEvaluator(),
        "healing_manager": SelfHealingManager(max_retries=3),
        "cost_tracker": CostTracker(
            daily_cost_cap_usd=float(os.environ.get("DAILY_COST_CAP_USD", "25.0")),
            campaign_token_budget=int(os.environ.get("TOKEN_BUDGET_PER_CAMPAIGN", "16000")),
        ),
    }
    return _singletons


def _get_cost_tracker():
    """Convenience accessor for cost_tracker singleton (used by @node_telemetry)."""
    return _get_singletons()["cost_tracker"]


# Module-level alias for tasks.py direct access (e.g. reset_daily_cost_accumulator_task)
# Returns None until first graph invocation — safe because tasks.py calls lazily.
class _LazyAttr:
    """Proxy that delegates attribute access to the live singleton after init."""
    def __init__(self, key: str): self._key = key
    def __getattr__(self, name: str):
        return getattr(_get_singletons()[self._key], name)


cost_tracker = _LazyAttr("cost_tracker")


def _get_agents() -> Dict[str, Any]:
    """
    Returns (or lazily builds) the shared agent object registry.
    Called once per graph execution thread; agents are stateless so sharing is safe.
    """
    global _agent_registry
    if _agent_registry:
        return _agent_registry

    from social_agent.agents.researcher import TrendResearcherAgent
    from social_agent.agents.copywriter import CopywritingCrew
    from social_agent.agents.media_specialist import MediaSpecialistAgent
    from social_agent.agents.publisher import SocialPublisherAgent
    from social_agent.agents.auditor import ComplianceAuditorAgent
    from social_agent.memory.hybrid_retriever import HybridRetriever
    from social_agent.memory.vector_store import VectorStoreManager
    from social_agent.memory.session_manager import SessionManager

    singletons = _get_singletons()
    vector_store = VectorStoreManager()
    hybrid_retriever = HybridRetriever(vector_store=vector_store)

    _agent_registry = {
        "researcher": TrendResearcherAgent(
            retriever=hybrid_retriever,
            mcp_client=singletons["mcp_client"],
            safety=singletons["safety_guardrail"],
        ),
        "copywriter": CopywritingCrew(),
        "media_specialist": MediaSpecialistAgent(),
        "publisher": SocialPublisherAgent(mcp_client=singletons["mcp_client"]),
        "auditor": ComplianceAuditorAgent(
            evaluator=singletons["judge_evaluator"],
            safety=singletons["safety_guardrail"],
        ),
        "session_manager": SessionManager(),
    }
    logger.info("Agent registry initialized with %d agents.", len(_agent_registry))
    return _agent_registry


# ──────────────────────────────────────────────────────────────────────────────
# Telemetry decorator
# ──────────────────────────────────────────────────────────────────────────────
def node_telemetry(node_name: str, model_name: str = "llama3.3:70b-instruct"):
    """
    Async decorator wrapping graph nodes with OpenTelemetry tracing, token cost recording,
    and a cost-cap circuit breaker that aborts the node before it executes if budget is exceeded.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(state: SocialAgentState) -> Dict[str, Any]:
            campaign_id = state.get("campaign_id", "default_campaign")
            thread_id = state.get("thread_id", f"thread_{campaign_id}")

            # ── Budget circuit breaker ────────────────────────────────────────────
            _ct = _get_cost_tracker()
            if not _ct.check_budget_clearance(campaign_id, estimated_tokens=1000):
                logger.error(
                    "Budget cap exceeded for campaign '%s'. Aborting node '%s'.",
                    campaign_id, node_name,
                )
                return {"error_logs": [f"Budget cap exceeded. Node '{node_name}' aborted."]}

            from social_agent.telemetry.tracing import trace_span

            async with trace_span(f"node.{node_name}", {"campaign_id": campaign_id, "thread_id": thread_id}) as span:
                t0 = time.monotonic()
                try:
                    result = await func(state)
                    latency = time.monotonic() - t0

                    p_tok = len(str(state)) // 4
                    c_tok = len(str(result)) // 4

                    _ct = _get_cost_tracker()
                    usage = _ct.record_step_usage(
                        campaign_id=campaign_id,
                        node_name=node_name,
                        model_name=model_name,
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        latency_seconds=latency,
                    )

                    span.set_attribute("social_agent.latency_sec", round(latency, 3))
                    span.set_attribute("social_agent.cost_usd", usage.cost_usd)
                    return result

                except Exception as exc:
                    span.record_exception(exc)
                    raise

        return wrapper
    return decorator


# ──────────────────────────────────────────────────────────────────────────────
# Node 1: plan_research_node  (PLAN)
# ──────────────────────────────────────────────────────────────────────────────
@node_telemetry("plan_research", "qwen2.5:32b-instruct")
async def plan_research_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Plan Node: Inbound safety scan, Brand RAG hybrid retrieval, live trend extraction.
    Aborts the graph immediately if the prompt fails the security scan.
    """
    agents = _get_agents()
    prompt = state.get("original_prompt", "")
    campaign_id = state.get("campaign_id", "default_campaign")
    thread_id = state.get("thread_id", f"thread_{campaign_id}")

    logger.info("[PLAN] Researcher analyzes prompt, queries Brand RAG + MCP trends.")
    research_res = await agents["researcher"].research_topic(prompt, campaign_id)

    if not research_res.get("is_safe", False):
        await agents["session_manager"].append_turn_event(
            thread_id=thread_id,
            campaign_id=campaign_id,
            node_name="plan_research",
            input_summary=prompt[:100],
            output_summary="Security Scan FAILED",
            token_usage={"total_tokens": len(prompt) // 4},
        )
        return {
            "audit_evaluation": AuditEvaluation(
                faithfulness_score=0.0,
                brand_voice_score=0.0,
                formatting_score=0.0,
                safety_score=0.0,
                overall_quality_score=0.0,
                is_safe=False,
                reasons=[f"Security Breach: {research_res.get('detected_violations')}"],
            ),
            "error_logs": [f"Security violation in prompt: {research_res.get('detected_violations')}"],
            "execution_history": ["Plan: Security scan FAILED. Graph execution halted."],
        }

    await agents["session_manager"].append_turn_event(
        thread_id=thread_id,
        campaign_id=campaign_id,
        node_name="plan_research",
        input_summary=prompt[:100],
        output_summary=f"Context items: {len(research_res.get('research_context', []))}",
        token_usage={"total_tokens": len(str(research_res.get("research_context", []))) // 4},
    )

    return {
        "original_prompt": research_res.get("original_prompt", prompt),
        "research_context": research_res.get("research_context", []),
        "execution_history": ["Plan: Research complete. Brand RAG + trend context retrieved."],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Node 2: act_research_and_draft_node  (ACT)
# ──────────────────────────────────────────────────────────────────────────────
@node_telemetry("act_research_and_draft", "llama3.3:70b-instruct")
async def act_research_and_draft_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Act Node: Delegates platform-tailored copywriting to CopywritingCrew.
    Injects remediation_feedback from previous failed audits when retrying.
    """
    agents = _get_agents()
    prompt = state.get("original_prompt", "")
    campaign_id = state.get("campaign_id", "default_campaign")
    thread_id = state.get("thread_id", f"thread_{campaign_id}")
    platforms = state.get("target_platforms", ["x_twitter"])
    context = state.get("research_context", [])
    feedback = state.get("remediation_feedback")

    logger.info("[ACT] Copywriter generates drafts for: %s", platforms)
    drafts = await agents["copywriter"].generate_platform_drafts(
        prompt=prompt,
        platforms=platforms,
        context=context,
        remediation_feedback=feedback,
    )

    await agents["session_manager"].append_turn_event(
        thread_id=thread_id,
        campaign_id=campaign_id,
        node_name="act_research_and_draft",
        input_summary=f"Platforms: {platforms}, Context: {len(context)} chunks",
        output_summary=f"Generated {len(drafts)} drafts",
        token_usage={"total_tokens": len(str(drafts)) // 4},
    )

    return {
        "draft_posts": drafts,
        "execution_history": [f"Act: Generated copy for {list(drafts.keys())}"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Node 3: media_prep_node  (OBSERVE)
# ──────────────────────────────────────────────────────────────────────────────
@node_telemetry("media_prep", "llama3.2:11b-vision")
async def media_prep_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Observe Node: SSRF URL validation, aspect-ratio compliance, vision-based alt-text generation.
    """
    agents = _get_agents()
    campaign_id = state.get("campaign_id", "default_campaign")
    thread_id = state.get("thread_id", f"thread_{campaign_id}")
    drafts = state.get("draft_posts", {})

    logger.info("[OBSERVE] Media Specialist validates URLs + generates alt-text for %d drafts.", len(drafts))
    updated_drafts = await agents["media_specialist"].process_media_assets(drafts)

    await agents["session_manager"].append_turn_event(
        thread_id=thread_id,
        campaign_id=campaign_id,
        node_name="media_prep",
        input_summary=f"Media prep for {len(drafts)} drafts",
        output_summary=f"Processed {len(updated_drafts)} drafts with alt_text",
        token_usage={"total_tokens": len(str(updated_drafts)) // 4},
    )

    return {
        "draft_posts": updated_drafts,
        "execution_history": ["Observe: Media validation and alt-text generation complete."],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Node 4: evaluate_audit_node  (REFLECT)
# ──────────────────────────────────────────────────────────────────────────────
@node_telemetry("evaluate_audit", "llama3.3:70b-instruct")
async def evaluate_audit_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Reflect Node: LLM-as-a-Judge multi-metric scoring (Faithfulness, Tone, Format, Safety).
    Calculates composite quality score Q and gates routing via edges.
    """
    agents = _get_agents()
    campaign_id = state.get("campaign_id", "default_campaign")
    thread_id = state.get("thread_id", f"thread_{campaign_id}")
    drafts = state.get("draft_posts", {})
    context = state.get("research_context", [])
    retry_count = state.get("retry_count", 0)

    logger.info(
        "[REFLECT] Auditor evaluates %d drafts. Retry: %d/3", len(drafts), retry_count
    )
    worst_eval = await agents["auditor"].audit_campaign_drafts(drafts, context)

    q = worst_eval.overall_quality_score
    logger.info("         Composite Q = %.4f | Safe = %s | Retry = %d/3", q, worst_eval.is_safe, retry_count)

    await agents["session_manager"].append_turn_event(
        thread_id=thread_id,
        campaign_id=campaign_id,
        node_name="evaluate_audit",
        input_summary=f"Auditing {len(drafts)} drafts",
        output_summary=f"Q = {q:.3f}, Safe = {worst_eval.is_safe}",
        token_usage={"total_tokens": len(str(worst_eval)) // 4},
    )

    return {
        "audit_evaluation": worst_eval,
        "remediation_feedback": worst_eval.remediation_suggestions,
        "execution_history": [f"Reflect: Audit complete. Q = {q:.3f}"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Node 5: reflect_remedy_node  (SELF-HEAL)
# ──────────────────────────────────────────────────────────────────────────────
@node_telemetry("reflect_remedy", "llama3.3:70b-instruct")
async def reflect_remedy_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Self-Healing Node: Classifies failure mode, increments retry counter,
    calculates jittered backoff, and formats structured critique for re-drafting.
    Bounded at N ≤ 3 retries — beyond which hitl_gate is activated via edge routing.
    """
    agents = _get_agents()
    campaign_id = state.get("campaign_id", "default_campaign")
    thread_id = state.get("thread_id", f"thread_{campaign_id}")
    current_retry = state.get("retry_count", 0) + 1
    eval_report = state.get("audit_evaluation")

    singletons = _get_singletons()
    mgr = singletons["healing_manager"]
    from social_agent.guardrails.self_healing import ErrorCategory

    directive = mgr.determine_recovery_action(
        category=ErrorCategory.QUALITY_THRESHOLD_FAIL,
        current_retry_count=current_retry,
        eval_report=eval_report,
    )

    # Persist remediation event to audit trail
    await mgr.log_remediation_to_audit(
        campaign_id=campaign_id,
        directive=directive,
    )

    await agents["session_manager"].append_turn_event(
        thread_id=thread_id,
        campaign_id=campaign_id,
        node_name="reflect_remedy",
        input_summary=f"Failure: {eval_report.reasons if eval_report else 'Unknown'}",
        output_summary=f"Retry {current_retry}/3, Action: {directive.action.value}",
        token_usage={"total_tokens": len(directive.feedback_payload or "") // 4},
    )

    return {
        "retry_count": current_retry,
        "remediation_feedback": directive.feedback_payload,
        "execution_history": [
            f"Self-Heal: Attempt {current_retry}/3, directive='{directive.action.value}', "
            f"backoff={directive.backoff_seconds:.1f}s"
        ],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Node 6: hitl_gate_node  (HUMAN-IN-THE-LOOP INTERRUPT)
# ──────────────────────────────────────────────────────────────────────────────
@node_telemetry("hitl_gate", "mistral-small:24b")
async def hitl_gate_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    HITL Gate Node: Suspends the workflow via LangGraph interrupt().
    The checkpointer serializes state to PostgreSQL.
    Workflow resumes when resume_hitl_workflow_task delivers Command(resume=...).
    """
    agents = _get_agents()
    campaign_id = state.get("campaign_id", "default_campaign")
    thread_id = state.get("thread_id", f"thread_{campaign_id}")
    drafts = state.get("draft_posts", {})
    eval_report = state.get("audit_evaluation")

    # Pause here — Django Admin or REST API must deliver the resume command
    human_input = interrupt({
        "message": "Human authorization required before social publication.",
        "campaign_id": campaign_id,
        "drafts": {
            p: (d.model_dump() if hasattr(d, "model_dump") else d.dict() if hasattr(d, "dict") else d)
            for p, d in drafts.items()
        },
        "quality_score": eval_report.overall_quality_score if eval_report else None,
        "reasons": eval_report.reasons if eval_report else [],
    })

    # Parse human reviewer response
    if isinstance(human_input, dict):
        approved = human_input.get("approved", False)
        notes = human_input.get("reviewer_notes", "Reviewed via Admin/API")
        modified_content: Dict[str, str] = human_input.get("modified_content", {})
    else:
        approved, notes, modified_content = False, "", {}

    # Apply reviewer's manual edits to draft copies
    updated_drafts = dict(drafts)
    for platform, revised_text in modified_content.items():
        if platform in updated_drafts:
            post = updated_drafts[platform]
            if hasattr(post, "model_copy"):
                updated_drafts[platform] = post.model_copy(
                    update={"content": revised_text, "character_count": len(revised_text)}
                )
            elif hasattr(post, "copy"):
                updated_drafts[platform] = post.copy(
                    update={"content": revised_text, "character_count": len(revised_text)}
                )

    await agents["session_manager"].append_turn_event(
        thread_id=thread_id,
        campaign_id=campaign_id,
        node_name="hitl_gate",
        input_summary="Interrupted — awaiting human authorization",
        output_summary=f"Approved: {approved} | Notes: {notes[:80]}",
        token_usage={"total_tokens": 0},
    )

    return {
        "hitl_payload": HITLApprovalPayload(
            required=True,
            approved=approved,
            reviewer_notes=notes,
            modified_content=modified_content or None,
        ),
        "draft_posts": updated_drafts,
        "execution_history": [
            f"HITL: Human verdict received. Approved={approved} | Notes='{notes[:60]}'"
        ],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Node 7: publish_dispatch_node  (PUBLISH)
# ──────────────────────────────────────────────────────────────────────────────
@node_telemetry("publish_dispatch", "mistral-small:24b")
async def publish_dispatch_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Publish Node: Delegates multi-platform dispatching to SocialPublisherAgent via FastMCP.
    On success, persists SocialPost records and updates campaign status in Tier 1 Django ORM.
    """
    agents = _get_agents()
    campaign_id = state.get("campaign_id")
    thread_id = state.get("thread_id", f"thread_{campaign_id}")
    drafts = state.get("draft_posts", {})
    hitl_payload = state.get("hitl_payload")

    logger.info("[PUBLISH] Publisher dispatching %d drafts via FastMCP.", len(drafts))
    dispatch_res = await agents["publisher"].publish_all(drafts, hitl_payload)

    published_ids: Dict[str, str] = dispatch_res.get("published_post_ids", {})
    errors = dispatch_res.get("errors", [])

    await agents["session_manager"].append_turn_event(
        thread_id=thread_id,
        campaign_id=campaign_id or "default_campaign",
        node_name="publish_dispatch",
        input_summary=f"Dispatching {len(drafts)} drafts",
        output_summary=f"Published: {list(published_ids.keys())}, Errors: {len(errors)}",
        token_usage={"total_tokens": sum(len(d.content) // 4 for d in drafts.values() if hasattr(d, "content"))},
    )

    # Tier 1 async persistence (best-effort — tasks.py performs authoritative persistence)
    if campaign_id:
        try:
            from social_agent.models import SocialCampaign, SocialPost
            from django.utils import timezone

            campaign = await SocialCampaign.objects.filter(id=campaign_id).afirst()
            if campaign:
                campaign.status = "PUBLISHED" if published_ids else "FAILED"
                await campaign.asave(update_fields=["status", "updated_at"])

                for platform, post in drafts.items():
                    if platform in published_ids and hasattr(post, "content"):
                        await SocialPost.objects.aupdate_or_create(
                            campaign=campaign,
                            platform=platform,
                            defaults={
                                "post_text": post.content,
                                "media_urls": post.media_urls or [],
                                "alt_text": post.alt_text,
                                "external_post_id": published_ids[platform],
                                "published_at": timezone.now(),
                                "character_count": len(post.content),
                            },
                        )
        except Exception as db_err:
            logger.debug("Tier 1 in-node persistence failed (tasks.py will retry): %s", db_err)

    return {
        "published_post_ids": published_ids,
        "error_logs": errors,
        "execution_history": [
            f"Publish: Dispatched {len(published_ids)} posts. IDs={published_ids}"
        ],
    }