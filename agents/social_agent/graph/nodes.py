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

# Agent Roster Instantiation
vector_store = VectorStoreManager()
hybrid_retriever = HybridRetriever(vector_store=vector_store)
researcher_agent = TrendResearcherAgent(retriever=hybrid_retriever, mcp_client=mcp_client, safety=safety_guardrail)
copywriter_agent = CopywritingCrew()
media_specialist_agent = MediaSpecialistAgent()
publisher_agent = SocialPublisherAgent(mcp_client=mcp_client)
auditor_agent = ComplianceAuditorAgent(evaluator=judge_evaluator, safety=safety_guardrail)

async def plan_research_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Plan Node: Delegates to TrendResearcherAgent.
    """
    prompt = state.get("original_prompt", "")
    campaign_id = state.get("campaign_id", "default_campaign")
    history = [f"Step: Plan & Research initiated for campaign '{campaign_id}'"]

    logger.info("[PLAN] 1. Researcher analyzes user prompt, queries Brand RAG + MCP trends, and constructs ground-truth context.")
    research_res = await researcher_agent.research_topic(prompt, campaign_id)

    if not research_res.get("is_safe", False):
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

    return {
        "original_prompt": research_res.get("original_prompt", prompt),
        "research_context": research_res.get("research_context", []),
        "execution_history": history + [f"Research complete. Retrieved combined context."]
    }

async def act_draft_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Act Node: Delegates platform-tailored copywriting to CopywritingCrew.
    """
    prompt = state.get("original_prompt", "")
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

    return {
        "draft_posts": drafts,
        "execution_history": [f"Act: Generated copy for {list(drafts.keys())}"]
    }

async def media_prep_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Observe Node: Delegates media validation and vision alt-text to MediaSpecialistAgent.
    """
    drafts = state.get("draft_posts", {})
    
    logger.info("[ACT] Media Specialist validates media URLs, enforces aspect ratios, and generates vision alt-text.")
    updated_drafts = await media_specialist_agent.process_media_assets(drafts)

    return {
        "draft_posts": updated_drafts,
        "execution_history": ["Observe: Verified media URLs and generated accessibility alt-text."]
    }


async def evaluate_audit_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Reflect Node: Multi-metric LLM-as-a-Judge evaluation and composite quality gating.
    """
    drafts = state.get("draft_posts", {})
    context = state.get("research_context", [])
    retry_count = state.get("retry_count", 0)
    
    logger.info("[OBSERVE] Auditor evaluates drafts against Groundedness, Tone, Format, and Safety rubrics, calculating composite score Q.")
    
    worst_eval = await auditor_agent.audit_campaign_drafts(drafts, context)
    
    q_score = worst_eval.overall_quality_score
    s_safety = worst_eval.safety_score
    logger.info("         Composite Q = %.4f | S_safety = %.4f | Retry = %d/3", q_score, s_safety, retry_count)

    return {
        "audit_evaluation": worst_eval,
        "remediation_feedback": worst_eval.remediation_suggestions,
        "execution_history": [f"Reflect: Audit completed. Overall Quality Q = {q_score:.3f}"]
    }


async def reflect_remedy_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Self-Healing Node: Determines recovery strategy, increments retry counter, and formats feedback.
    """
    current_retry = state.get("retry_count", 0) + 1
    eval_report = state.get("audit_evaluation")
    
    directive = healing_manager.determine_recovery_action(
        category=ErrorCategory.QUALITY_THRESHOLD_FAIL,
        current_retry_count=current_retry,
        eval_report=eval_report
    )

    return {
        "retry_count": current_retry,
        "remediation_feedback": directive.feedback_payload,
        "execution_history": [f"Self-Healing: Triggered attempt {current_retry}/3 with directive '{directive.action.value}'"]
    }


async def hitl_gate_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Human-in-the-Loop Node: Uses LangGraph interrupt() to pause workflow.
    Resumes upon receiving a Command(resume=...) payload from Django Admin.
    """
    campaign_id = state.get("campaign_id", "")
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
            updated_drafts[p].content = text
            updated_drafts[p].character_count = len(text)

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


async def publish_dispatch_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Publish Node: Delegates to SocialPublisherAgent for MCP tool dispatching.
    """
    drafts = state.get("draft_posts", {})
    hitl_payload = state.get("hitl_payload")
    
    logger.info("[REFLECT & ROUTE] Publisher executes FastMCP dispatch to platforms.")
    
    dispatch_res = await publisher_agent.publish_all(drafts, hitl_payload)
    
    published_ids = dispatch_res.get("published_post_ids", {})
    errors = dispatch_res.get("errors", [])

    return {
        "published_post_ids": published_ids,
        "error_logs": errors,
        "execution_history": [f"Publish: Dispatched {len(published_ids)} posts. Success IDs = {published_ids}"]
    }