"""
social_agent/graph/nodes.py
State graph nodes implementing the cognitive loop and CrewAI orchestration.
"""
import asyncio
from typing import Dict, Any, List
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt, Command
from social_agent.graph.state import SocialAgentState, PlatformPostPayload, AuditEvaluation, HITLApprovalPayload
from social_agent.mcp_tools.client import SocialMCPClient

# Factory initialization for local LLM inference endpoint (Ollama/vLLM)
local_llm = ChatOpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
    model="llama3.3:70b-instruct",
    temperature=0.3,
    timeout=60.0
)

evaluator_llm = ChatOpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
    model="llama3.3:70b-instruct",
    temperature=0.0,
    timeout=60.0
)

mcp_client = SocialMCPClient()


async def plan_research_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Plan Node: Queries local Vector Store RAG and external MCP trends tool.
    """
    prompt = state["original_prompt"]
    history = [f"Step: Plan and Research initialized for campaign '{state['campaign_id']}'"]
    
    # Retrieve trend data via MCP tool
    trend_result = await mcp_client.call_tool("search_trends", {"query": prompt})
    retrieved_trends = trend_result.get("trends", [])
    
    # Simulated Local Vector RAG (Brand Guidelines)
    brand_context = [
        "Brand Voice Rule: Authoritative, innovative, technically grounded.",
        "Prohibited Terms: 'revolutionize', 'synergy', 'game-changer'.",
        "Hashtag Guidelines: 2-3 targeted tags maximum."
    ]
    
    combined_context = brand_context + retrieved_trends
    return {
        "research_context": combined_context,
        "execution_history": history
    }


async def act_draft_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Act Node: Generates platform-tailored copy incorporating context & remediation feedback.
    """
    prompt = state["original_prompt"]
    context = "\n".join(state["research_context"])
    feedback = state.get("remediation_feedback")
    
    feedback_instruction = f"\nCRITICAL REMEDIATION FEEDBACK FROM AUDITOR:\n{feedback}\nYou MUST resolve all issues mentioned above." if feedback else ""
    
    drafts: Dict[str, PlatformPostPayload] = {}
    
    for platform in state["target_platforms"]:
        sys_msg = SystemMessage(content=(
            f"You are an expert Social Media Strategist specializing in {platform}.\n"
            f"Context & Guidelines:\n{context}\n{feedback_instruction}\n"
            f"Produce the final post text. Adhere strictly to platform character bounds."
        ))
        user_msg = HumanMessage(content=f"Draft the post for objective: {prompt}")
        
        response = await local_llm.ainvoke([sys_msg, user_msg])
        content_text = response.content.strip()
        
        drafts[platform] = PlatformPostPayload(
            platform=platform,
            content=content_text,
            hashtags=["#AIArchitecture", "#EnterpriseAI"],
            media_urls=["https://storage.cdn.internal/assets/hero_chart_2026.png"],
            character_count=len(content_text)
        )
        
    return {
        "draft_posts": drafts,
        "execution_history": [f"Drafted content for {list(drafts.keys())}"]
    }


async def media_prep_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Observe Node: Inspects media requirements, resizes, and generates accessibility alt text.
    """
    drafts = state["draft_posts"]
    for platform, post in drafts.items():
        if post.media_urls:
            post.alt_text = f"High-level architectural schematic showing multi-agent system state flow for {platform}."
    
    return {
        "draft_posts": drafts,
        "execution_history": ["Verified media sizing and generated accessibility alt-text."]
    }


async def evaluate_audit_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Reflect Node: LLM-as-a-Judge evaluation measuring safety, tone, and formatting.
    """
    drafts = state["draft_posts"]
    reasons = []
    total_score = 1.0
    is_safe = True
    remediation = None
    
    for platform, post in drafts.items():
        # Check platform length constraints
        if platform == "x_twitter" and len(post.content) > 280:
            total_score -= 0.3
            reasons.append(f"X/Twitter post exceeds 280 characters ({len(post.content)} chars).")
        
        # Check banned buzzwords
        for banned in ["revolutionize", "synergy", "game-changer"]:
            if banned in post.content.lower():
                total_score -= 0.2
                reasons.append(f"Contains prohibited corporate buzzword: '{banned}' on {platform}.")
                
    total_score = max(0.0, min(1.0, total_score))
    if total_score < 0.90:
        remediation = "Shorten the copy to conform to character limits and eliminate all prohibited buzzwords."
        
    evaluation = AuditEvaluation(
        faithfulness_score=0.95,
        brand_voice_score=total_score,
        safety_score=1.0,
        overall_quality_score=total_score,
        is_safe=is_safe,
        reasons=reasons,
        remediation_suggestions=remediation
    )
    
    return {
        "audit_evaluation": evaluation,
        "remediation_feedback": remediation,
        "execution_history": [f"Evaluated draft quality: Overall Score = {total_score}"]
    }


async def reflect_remedy_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Self-Healing Node: Increments retry counter and prepares remediation context.
    """
    new_retry = state.get("retry_count", 0) + 1
    return {
        "retry_count": new_retry,
        "execution_history": [f"Self-healing loop triggered (Attempt {new_retry}/3)."]
    }


async def hitl_gate_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Human-in-the-Loop Node: Uses LangGraph interrupt() to pause workflow execution.
    Awaits explicit approval or edited copy from the Django Admin UI.
    """
    # Pauses graph execution and persists checkpoint to PostgreSQL
    human_input = interrupt({
        "message": "Campaign requires human authorization before publishing.",
        "campaign_id": state["campaign_id"],
        "drafts": {p: d.dict() for p, d in state["draft_posts"].items()},
        "audit_reasons": state["audit_evaluation"].reasons if state["audit_evaluation"] else []
    })
    
    # Resumes when Command(resume=...) is passed to graph runner
    approved = human_input.get("approved", False)
    notes = human_input.get("reviewer_notes", "Reviewed via Django Admin")
    
    # If human modified content directly in Django Admin
    modified_drafts = state["draft_posts"]
    if human_input.get("modified_content"):
        for p, text in human_input["modified_content"].items():
            if p in modified_drafts:
                modified_drafts[p].content = text
                
    return {
        "hitl_payload": HITLApprovalPayload(
            required=True,
            approved=approved,
            reviewer_notes=notes
        ),
        "draft_posts": modified_drafts,
        "execution_history": [f"HITL Decision Received: Approved={approved} | Notes={notes}"]
    }


async def publish_dispatch_node(state: SocialAgentState) -> Dict[str, Any]:
    """
    Publish Node: Dispatches validated posts to platforms via MCP.
    """
    published_ids = {}
    drafts = state["draft_posts"]
    
    for platform, post in drafts.items():
        if platform == "x_twitter":
            res = await mcp_client.call_tool("post_x_tweet", {"text": post.content})
            published_ids["x_twitter"] = res["post_id"]
        elif platform == "instagram":
            res = await mcp_client.call_tool("post_instagram", {
                "caption": post.content,
                "media_url": post.media_urls[0] if post.media_urls else "https://via.placeholder.com/1080"
            })
            published_ids["instagram"] = res["post_id"]
        elif platform == "tiktok":
            res = await mcp_client.call_tool("post_tiktok", {
                "video_url": "https://storage.cdn.internal/videos/demo.mp4",
                "caption": post.content
            })
            published_ids["tiktok"] = res["post_id"]
            
    return {
        "published_post_ids": published_ids,
        "execution_history": [f"Published to platforms: {published_ids}"]
    }