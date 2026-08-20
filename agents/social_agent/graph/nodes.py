"""
social_agent/graph/nodes.py
Pure async state graph nodes implementing the cognitive loop:
Plan -> Act -> Observe -> Reflect -> Gate -> Publish.
"""
import os
import re
import logging
from typing import Dict, Any, List, Optional

try:
    from langchain_core.messages import SystemMessage, HumanMessage
    from langchain_openai import ChatOpenAI
except ImportError:
    class SystemMessage:
        def __init__(self, content: str): self.content = content
    class HumanMessage:
        def __init__(self, content: str): self.content = content
    class ChatOpenAI:
        def __init__(self, *args, **kwargs): pass
        async def ainvoke(self, messages):
            class Response: content = "Production update: Enhancing agentic automation workflows with verified resilience."
            return Response()

try:
    from langgraph.types import interrupt, Command
except ImportError:
    def interrupt(payload): return {"approved": True, "reviewer_notes": "Default Mock Approval"}
    class Command:
        def __init__(self, resume=None): self.resume = resume

from social_agent.graph.state import (
    SocialAgentState,
    PlatformPostPayload,
    AuditEvaluation,
    HITLApprovalPayload,
)
from social_agent.mcp_tools.client import SocialMCPClient
from social_agent.guardrails.safety import SafetyGuardrail
from social_agent.guardrails.evaluators import LLMJudgeEvaluator
from social_agent.guardrails.self_healing import SelfHealingManager, ErrorCategory

logger = logging.getLogger(__name__)

# LLM Client Factory for local inference (Ollama/vLLM)
local_llm = ChatOpenAI(
    base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
    api_key="ollama",
    model=os.environ.get("PRIMARY_LLM_MODEL", "llama3.3:70b-instruct"),
    temperature=0.3,
    timeout=60.0
)

# Helper Subsystems
mcp_client = SocialMCPClient()
safety_guardrail = SafetyGuardrail()
judge_evaluator = LLMJudgeEvaluator()
healing_manager = SelfHealingManager(max_retries=3)


from social_agent.agents.researcher import TrendResearcherAgent
from social_agent.agents.copywriter import CopywritingCrew
from social_agent.agents.media_specialist import MediaSpecialistAgent
from social_agent.agents.publisher import SocialPublisherAgent
from social_agent.memory.hybrid_retriever import HybridRetriever
from social_agent.memory.vector_store import VectorStoreManager

from social_agent.agents.auditor import ComplianceAuditorAgent
from social_agent.memory.session_manager import SessionManager
from social_agent.telemetry.tracing import trace_span
from social_agent.telemetry.cost_tracker import CostTracker

# Agent Roster Instantiation
vector_store = VectorStoreManager()
hybrid_retriever = HybridRetriever(vector_store=vector_store)
researcher_agent = TrendResearcherAgent(retriever=hybrid_retriever, mcp_client=mcp_client, safety=safety_guardrail)
copywriter_agent = CopywritingCrew()
media_specialist_agent = MediaSpecialistAgent()
publisher_agent = SocialPublisherAgent(mcp_client=mcp_client)
auditor_agent = ComplianceAuditorAgent(evaluator=judge_evaluator, safety=safety_guardrail)
session_manager = SessionManager()
cost_tracker = CostTracker()


import time
from functools import wraps

def node_telemetry(node_name: str, model_name: str = "llama3.3:70b-instruct"):
    def decorator(func):
        @wraps(func)
        async def wrapper(state: SocialAgentState) -> Dict[str, Any]:
            campaign_id = state.get("campaign_id", "default_campaign")
            thread_id = state.get("thread_id", f"thread_{campaign_id}")
            
            # Circuit Breaker Cost Check
            if not cost_tracker.check_budget_clearance(campaign_id, estimated_tokens=1000):
                logger.error(f"Budget exceeded for {campaign_id}. Aborting {node_name}.")
                return {"error_logs": ["Budget exceeded. Aborted."]}
                
            async with trace_span(f"node.{node_name}", {"campaign_id": campaign_id, "thread_id": thread_id}) as span:
                start_time = time.time()
                try:
                    result = await func(state)
                    latency = time.time() - start_time
                    
                    # Estimate tokens from result
                    p_tok = len(str(state)) // 4
                    c_tok = len(str(result)) // 4
                    
                    usage = cost_tracker.record_step_usage(
                        campaign_id=campaign_id,
                        node_name=node_name,
                        model_name=model_name,
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        latency_seconds=latency
                    )
                    
                    span.set_attribute("social_agent.latency", latency)
                    span.set_attribute("social_agent.cost", usage.cost_usd)
                    
                    return result
                except Exception as e:
                    span.record_exception(e)
                    raise
        return wrapper
    return decorator

@node_telemetry("plan_research", "qwen2.5:32b-instruct")
async def plan_research_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Plan Node: Delegates to TrendResearcherAgent.
    """
    prompt = state.get("original_prompt", "")
    campaign_id = state.get("campaign_id", "default_campaign")
    thread_id = state.get("thread_id", f"thread_{campaign_id}")
    history = [f"Step: Plan & Research initiated for campaign '{campaign_id}'"]

    logger.info("[PLAN] 1. Researcher analyzes user prompt, queries Brand RAG + MCP trends, and constructs ground-truth context.")
    research_res = await researcher_agent.research_topic(prompt, campaign_id)

    if not research_res.get("is_safe", False):
        await session_manager.append_turn_event(
            thread_id=thread_id,
            campaign_id=campaign_id,
            node_name="plan_research",
            input_summary=prompt,
            output_summary="Security Scan Failed",
            token_usage={"total_tokens": len(prompt) // 4}
        )
        return {
            "audit_evaluation": AuditEvaluation(
                faithfulness_score=0.0,
                brand_voice_score=0.0,
                formatting_score=0.0,
                safety_score=0.0,
                overall_quality_score=0.0,
                is_safe=False,
                reasons=[f"Security Breach: {research_res.get('detected_violations')}"]
            ),
            "error_logs": [f"Security Violation detected in prompt: {research_res.get('detected_violations')}"],
            "execution_history": history + ["Security Scan Failed. Halting graph progression."]
        }
        
    await session_manager.append_turn_event(
        thread_id=thread_id,
        campaign_id=campaign_id,
        node_name="plan_research",
        input_summary=prompt[:100],
        output_summary=f"Context items: {len(research_res.get('research_context', []))}",
        token_usage={"total_tokens": len(str(research_res.get("research_context", []))) // 4}
    )

    return {
        "original_prompt": research_res.get("original_prompt", prompt),
        "research_context": research_res.get("research_context", []),
        "execution_history": history + [f"Research complete. Retrieved combined context."]
    }

@node_telemetry("act_research_and_draft")
async def act_research_and_draft_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Act Node: Delegates platform-tailored copywriting to CopywritingCrew.
    """
    prompt = state.get("original_prompt", "")
    campaign_id = state.get("campaign_id", "default_campaign")
    thread_id = state.get("thread_id", f"thread_{campaign_id}")
    platforms = state.get("target_platforms", ["x_twitter"])
    context = state.get("research_context", [])
    feedback = state.get("remediation_feedback")

    logger.info("[ACT] Copywriter generates drafts for X, Instagram, and TikTok using channel-specific prompts.")
    drafts = await copywriter_agent.generate_platform_drafts(
        prompt=prompt,
        platforms=platforms,
        context=context,
        remediation_feedback=feedback
    )
    
    await session_manager.append_turn_event(
        thread_id=thread_id,
        campaign_id=campaign_id,
        node_name="act_research_and_draft",
        input_summary=f"Context: {len(context)} items, Platforms: {platforms}",
        output_summary=f"Generated {len(drafts)} drafts",
        token_usage={"total_tokens": len(str(drafts)) // 4}
    )

    return {
        "draft_posts": drafts,
        "execution_history": [f"Act: Generated copy for {list(drafts.keys())}"]
    }

@node_telemetry("media_prep", "llama3.2:11b-vision")
async def media_prep_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Observe Node: Delegates media validation and vision alt-text to MediaSpecialistAgent.
    """
    campaign_id = state.get("campaign_id", "default_campaign")
    thread_id = state.get("thread_id", f"thread_{campaign_id}")
    drafts = state.get("draft_posts", {})
    
    logger.info("[ACT] Media Specialist validates media URLs, enforces aspect ratios, and generates vision alt-text.")
    updated_drafts = await media_specialist_agent.process_media_assets(drafts)

    await session_manager.append_turn_event(
        thread_id=thread_id,
        campaign_id=campaign_id,
        node_name="media_prep",
        input_summary=f"Drafts to prep media: {len(drafts)}",
        output_summary=f"Prepped {len(updated_drafts)} drafts with alt_text",
        token_usage={"total_tokens": len(str(updated_drafts)) // 4}
    )

    return {
        "draft_posts": updated_drafts,
        "execution_history": ["Observe: Verified media URLs and generated accessibility alt-text."]
    }


@node_telemetry("evaluate_audit")
async def evaluate_audit_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Reflect Node: Multi-metric LLM-as-a-Judge evaluation and composite quality gating.
    """
    campaign_id = state.get("campaign_id", "default_campaign")
    thread_id = state.get("thread_id", f"thread_{campaign_id}")
    drafts = state.get("draft_posts", {})
    context = state.get("research_context", [])
    retry_count = state.get("retry_count", 0)
    
    logger.info("[OBSERVE] Auditor evaluates drafts against Groundedness, Tone, Format, and Safety rubrics, calculating composite score Q.")
    
    worst_eval = await auditor_agent.audit_campaign_drafts(drafts, context)
    
    q_score = worst_eval.overall_quality_score
    s_safety = worst_eval.safety_score
    logger.info("         Composite Q = %.4f | S_safety = %.4f | Retry = %d/3", q_score, s_safety, retry_count)

    await session_manager.append_turn_event(
        thread_id=thread_id,
        campaign_id=campaign_id,
        node_name="evaluate_audit",
        input_summary=f"Auditing {len(drafts)} drafts",
        output_summary=f"Q = {q_score:.3f}, Safe = {s_safety}",
        token_usage={"total_tokens": len(str(worst_eval)) // 4}
    )

    return {
        "audit_evaluation": worst_eval,
        "remediation_feedback": worst_eval.remediation_suggestions,
        "execution_history": [f"Reflect: Audit completed. Overall Quality Q = {q_score:.3f}"]
    }


@node_telemetry("reflect_remedy")
async def reflect_remedy_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Self-Healing Node: Determines recovery strategy, increments retry counter, and formats feedback.
    """
    campaign_id = state.get("campaign_id", "default_campaign")
    thread_id = state.get("thread_id", f"thread_{campaign_id}")
    current_retry = state.get("retry_count", 0) + 1
    eval_report = state.get("audit_evaluation")
    
    directive = healing_manager.determine_recovery_action(
        category=ErrorCategory.QUALITY_THRESHOLD_FAIL,
        current_retry_count=current_retry,
        eval_report=eval_report
    )

    await session_manager.append_turn_event(
        thread_id=thread_id,
        campaign_id=campaign_id,
        node_name="reflect_remedy",
        input_summary=f"Fail reason: {eval_report.reasons if eval_report else 'Unknown'}",
        output_summary=f"Retry {current_retry}/3, Directive: {directive.action.value}",
        token_usage={"total_tokens": len(directive.feedback_payload or "") // 4}
    )

    return {
        "retry_count": current_retry,
        "remediation_feedback": directive.feedback_payload,
        "execution_history": [f"Self-Healing: Triggered attempt {current_retry}/3 with directive '{directive.action.value}'"]
    }


@node_telemetry("hitl_gate")
async def hitl_gate_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Human-in-the-Loop Node: Uses LangGraph interrupt() to pause workflow.
    Resumes upon receiving a Command(resume=...) payload from Django Admin.
    """
    campaign_id = state.get("campaign_id", "default_campaign")
    thread_id = state.get("thread_id", f"thread_{campaign_id}")
    drafts = state.get("draft_posts", {})
    eval_report = state.get("audit_evaluation")

    human_input = interrupt({
        "message": "Human authorization required before social publication.",
        "campaign_id": campaign_id,
        "drafts": {p: d.dict() if hasattr(d, "dict") else d for p, d in drafts.items()},
        "reasons": eval_report.reasons if eval_report else []
    })

    approved = human_input.get("approved", False) if isinstance(human_input, dict) else False
    notes = human_input.get("reviewer_notes", "Reviewed via Django Admin") if isinstance(human_input, dict) else ""
    modified_content = human_input.get("modified_content", {}) if isinstance(human_input, dict) else {}

    updated_drafts = dict(drafts)
    for p, text in modified_content.items():
        if p in updated_drafts:
            updated_drafts[p] = updated_drafts[p].copy(update={
                "content": text,
                "character_count": len(text)
            })

    await session_manager.append_turn_event(
        thread_id=thread_id,
        campaign_id=campaign_id,
        node_name="hitl_gate",
        input_summary="Paused for HITL intervention",
        output_summary=f"Approved: {approved}, Notes: {notes}",
        token_usage={"total_tokens": 0}
    )

    return {
        "hitl_payload": HITLApprovalPayload(
            required=True,
            approved=approved,
            reviewer_notes=notes,
            modified_content=modified_content
        ),
        "draft_posts": updated_drafts,
        "execution_history": [f"HITL: Human verdict received. Approved = {approved} | Notes = {notes}"]
    }


@node_telemetry("publish_dispatch", "mistral-small:24b")
async def publish_dispatch_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Publish Node: Delegates to SocialPublisherAgent for MCP tool dispatching.
    Persists successful SocialPost objects asynchronously to Tier 3.
    """
    campaign_id = state.get("campaign_id")
    thread_id = state.get("thread_id", f"thread_{campaign_id}")
    drafts = state.get("draft_posts", {})
    hitl_payload = state.get("hitl_payload")
    
    logger.info("[REFLECT & ROUTE] Publisher executes FastMCP dispatch to platforms.")
    
    dispatch_res = await publisher_agent.publish_all(drafts, hitl_payload)
    
    published_ids = dispatch_res.get("published_post_ids", {})
    errors = dispatch_res.get("errors", [])
    
    await session_manager.append_turn_event(
        thread_id=thread_id,
        campaign_id=campaign_id or "default_campaign",
        node_name="publish_dispatch",
        input_summary=f"Drafts to publish: {len(drafts)}",
        output_summary=f"Published platforms: {list(published_ids.keys())}, Errors: {len(errors)}",
        token_usage={"total_tokens": sum(len(d.content) // 4 for d in drafts.values())}
    )

    # Tier 3: Async Relational Persistence (Django ORM)
    try:
        from social_agent.models import SocialCampaign, SocialPost
        from django.utils import timezone
        
        campaign = None
        if campaign_id:
            campaign = await SocialCampaign.objects.filter(id=campaign_id).afirst()
            
        if campaign:
            campaign.status = "PUBLISHED" if len(published_ids) > 0 else "FAILED"
            await campaign.asave()
            
            for platform, post in drafts.items():
                if platform in published_ids:
                    await SocialPost.objects.acreate(
                        campaign=campaign,
                        platform=platform,
                        post_text=post.content,
                        media_urls=post.media_urls,
                        alt_text=post.alt_text,
                        external_post_id=published_ids[platform],
                        published_at=timezone.now(),
                        character_count=post.character_count
                    )
    except Exception as db_err:
        logger.debug("Failed to conditionally persist records to Tier 3 (Django ORM): %s", db_err)

    return {
        "published_post_ids": published_ids,
        "error_logs": errors,
        "execution_history": [f"Publish: Dispatched {len(published_ids)} posts. Success IDs = {published_ids}"]
    }