"""
social_agent/tasks.py
Celery background workers orchestrating compiled LangGraph state machine execution and HITL resumption.

Architectural invariants enforced here:
- Never execute LangGraph streaming inside Django HTTP request threads (always async via Celery).
- Never call task.delay() inside atomic DB blocks — use transaction.on_commit() (enforced in views.py).
- Isolated asyncio event loop per task (asyncio.run) to prevent cross-task loop contamination.
"""
import os
import asyncio
import logging
from datetime import timezone as tz

from celery import shared_task
from django.conf import settings
from langgraph.types import Command

from social_agent.models import SocialCampaign, SocialPost
from social_agent.graph.workflow import create_social_agent_graph
from social_agent.graph.checkpointer import get_postgres_checkpointer

logger = logging.getLogger("social_agent")


# ──────────────────────────────────────────────────────────────────────────────
# Helper: Resolve initial state dict from campaign record
# ──────────────────────────────────────────────────────────────────────────────
def _build_initial_state(campaign: SocialCampaign) -> dict:
    from social_agent.graph.state import HITLApprovalPayload
    return {
        "campaign_id": str(campaign.id),
        "thread_id": campaign.langgraph_thread_id,
        "original_prompt": campaign.raw_prompt,
        "target_platforms": campaign.target_platforms,
        "research_context": [],
        "query_rewrite_count": 0,
        "draft_posts": {},
        "audit_evaluation": None,
        "retry_count": 0,
        "remediation_feedback": None,
        "hitl_payload": HITLApprovalPayload(required=False),
        "published_post_ids": {},
        "error_logs": [],
        "execution_history": [],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Helper: Persist published posts to Django ORM
# ──────────────────────────────────────────────────────────────────────────────
async def _persist_published_posts(campaign: SocialCampaign, final_state: dict) -> None:
    """Async helper persisting SocialPost records after successful publication."""
    from django.utils import timezone

    published_ids: dict = final_state.get("published_post_ids", {})
    drafts: dict = final_state.get("draft_posts", {})

    for platform, post_data in drafts.items():
        ext_id = published_ids.get(platform)
        if not ext_id:
            continue  # Skip platforms that were not successfully published

        if hasattr(post_data, "content"):
            content = post_data.content
            media_urls = post_data.media_urls
            alt_text = post_data.alt_text
        else:
            content = str(post_data.get("content", ""))
            media_urls = post_data.get("media_urls", [])
            alt_text = post_data.get("alt_text")

        try:
            await SocialPost.objects.acreate(
                campaign=campaign,
                platform=platform,
                post_text=content,
                media_urls=media_urls or [],
                alt_text=alt_text,
                external_post_id=ext_id,
                published_at=timezone.now(),
                character_count=len(content),
            )
        except Exception as persist_err:
            logger.error(
                "Failed to persist SocialPost for campaign '%s', platform '%s': %s",
                campaign.id, platform, persist_err
            )


# ──────────────────────────────────────────────────────────────────────────────
# Task 1: Launch full campaign workflow
# ──────────────────────────────────────────────────────────────────────────────
@shared_task(bind=True, max_retries=2, autoretry_for=(Exception,), retry_backoff=3, ignore_result=True)
def run_campaign_workflow_task(self, campaign_id: str):
    """
    Asynchronously executes the multi-agent social media campaign workflow.
    Dispatched after transaction.on_commit() by TriggerCampaignView to guarantee
    database record existence before the Celery worker fetches it.

    Args:
        campaign_id: UUID string of the SocialCampaign record to execute.
    """
    logger.info("Celery worker started: run_campaign_workflow_task for campaign '%s'", campaign_id)

    async def _execute():
        # ── Step 1: Mark campaign as RUNNING ─────────────────────────────
        campaign = await SocialCampaign.objects.aget(id=campaign_id)
        campaign.status = "RUNNING"
        await campaign.asave(update_fields=["status", "updated_at"])

        # ── Step 2: Initialize AsyncPostgresSaver checkpointer ────────────
        postgres_url = getattr(settings, "POSTGRES_POOL_URL", None) or os.environ.get("POSTGRES_POOL_URL")
        checkpointer = await get_postgres_checkpointer(conn_string=postgres_url)

        # ── Step 3: Compile the graph ─────────────────────────────────────
        graph = create_social_agent_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": campaign.langgraph_thread_id}}
        initial_state = _build_initial_state(campaign)

        # ── Step 4: Stream graph execution, capturing any interrupt ───────
        try:
            async for _event in graph.astream(initial_state, config=config, stream_mode="values"):
                pass  # Events are captured by node telemetry decorators
        except Exception as stream_err:
            logger.error(
                "Graph streaming error on campaign '%s': %s", campaign_id, stream_err, exc_info=True
            )

        # ── Step 5: Inspect final state snapshot ──────────────────────────
        # agt_state() is the async variant — critical correctness fix.
        state_snapshot = await graph.aget_state(config)

        # Detect HITL interrupt: graph is paused waiting at hitl_gate node
        if state_snapshot.next and any("hitl_gate" in str(n) for n in state_snapshot.next):
            logger.info("Campaign '%s' paused at HITL approval gate.", campaign_id)
            campaign.status = "AWAITING_APPROVAL"
            await campaign.asave(update_fields=["status", "updated_at"])
            return "PAUSED_AT_HITL"

        # ── Step 6: Finalize campaign state ───────────────────────────────
        final_state = state_snapshot.values if hasattr(state_snapshot, "values") else {}
        eval_report = final_state.get("audit_evaluation")
        published_ids: dict = final_state.get("published_post_ids", {})

        if eval_report:
            campaign.overall_quality_score = float(eval_report.overall_quality_score)
            campaign.safety_passed = bool(eval_report.is_safe)

        if published_ids:
            campaign.status = "PUBLISHED"
            await _persist_published_posts(campaign, final_state)
        elif final_state.get("error_logs"):
            campaign.status = "FAILED"
        else:
            campaign.status = "FAILED"

        await campaign.asave(update_fields=["status", "overall_quality_score", "safety_passed", "updated_at"])
        logger.info("Campaign '%s' completed with final status '%s'", campaign_id, campaign.status)
        return campaign.status

    return asyncio.run(_execute())


# ──────────────────────────────────────────────────────────────────────────────
# Task 2: Resume HITL-interrupted workflow
# ──────────────────────────────────────────────────────────────────────────────
@shared_task(bind=True, max_retries=2, ignore_result=True)
def resume_hitl_workflow_task(
    self,
    campaign_id: str,
    approved: bool,
    reviewer_notes: str,
    modified_content: dict,
):
    """
    Resumes an interrupted LangGraph workflow thread by passing a signed Command(resume=...) payload.
    Dispatched after transaction.on_commit() by HITLApprovalView to synchronize DB state first.

    Args:
        campaign_id: UUID of the SocialCampaign.
        approved: Human reviewer verdict (True = publish, False = reject).
        reviewer_notes: Audit rationale string from reviewer.
        modified_content: Optional per-platform copy edits from reviewer.
    """
    logger.info(
        "Celery worker started: resume_hitl_workflow_task for campaign '%s' [Approved: %s]",
        campaign_id, approved
    )

    async def _resume():
        campaign = await SocialCampaign.objects.aget(id=campaign_id)
        postgres_url = getattr(settings, "POSTGRES_POOL_URL", None) or os.environ.get("POSTGRES_POOL_URL")
        checkpointer = await get_postgres_checkpointer(conn_string=postgres_url)

        graph = create_social_agent_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": campaign.langgraph_thread_id}}

        resume_payload = {
            "approved": approved,
            "reviewer_notes": reviewer_notes or "Reviewed via API/Admin",
            "modified_content": modified_content or {},
        }

        # Dispatch Command(resume=...) to wake the interrupted hitl_gate node
        try:
            async for _event in graph.astream(
                Command(resume=resume_payload), config=config, stream_mode="values"
            ):
                pass
        except Exception as stream_err:
            logger.error(
                "Graph resume streaming error on campaign '%s': %s", campaign_id, stream_err, exc_info=True
            )

        # Inspect final state after resumption
        state_snapshot = await graph.aget_state(config)
        final_state = state_snapshot.values if hasattr(state_snapshot, "values") else {}
        published_ids: dict = final_state.get("published_post_ids", {})

        if approved and published_ids:
            campaign.status = "PUBLISHED"
            await _persist_published_posts(campaign, final_state)
        elif not approved:
            campaign.status = "REJECTED"
        else:
            campaign.status = "FAILED"

        eval_report = final_state.get("audit_evaluation")
        if eval_report:
            campaign.overall_quality_score = float(eval_report.overall_quality_score)
            campaign.safety_passed = bool(eval_report.is_safe)

        await campaign.asave(update_fields=["status", "overall_quality_score", "safety_passed", "updated_at"])
        logger.info(
            "Resumed campaign '%s' finalized with status '%s'", campaign_id, campaign.status
        )
        return campaign.status

    return asyncio.run(_resume())


# ──────────────────────────────────────────────────────────────────────────────
# Task 3: Periodic Celery Beat — daily cost accumulator reset
# ──────────────────────────────────────────────────────────────────────────────
@shared_task(ignore_result=True)
def reset_daily_cost_accumulator_task():
    """
    Scheduled via Celery Beat every 24 hours.
    Clears the rolling daily cost accumulator in the CostTracker singleton.
    """
    try:
        from social_agent.graph.nodes import cost_tracker
        cost_tracker.reset_daily_accumulator()
        logger.info("Daily cost accumulator reset by Celery Beat.")
    except Exception as err:
        logger.warning("Failed to reset cost accumulator: %s", err)