"""
social_agent/tasks.py
Celery background workers orchestrating compiled LangGraph state machine execution and HITL resumption.
"""
import os
import asyncio
import logging
from celery import shared_task
from django.conf import settings
from langgraph.types import Command

from social_agent.models import SocialCampaign, SocialPost
from social_agent.graph.workflow import create_social_agent_graph
from social_agent.graph.checkpointer import get_postgres_checkpointer

logger = logging.getLogger("social_agent")


@shared_task(bind=True, max_retries=2, autoretry_for=(Exception,), retry_backoff=3)
def run_campaign_workflow_task(self, campaign_id: str):
    """
    Asynchronously executes a multi-agent social media campaign workflow inside an isolated event loop.

    Args:
        campaign_id: UUID of the SocialCampaign record.
    """
    logger.info("Celery task started: run_campaign_workflow_task for campaign '%s'", campaign_id)

    async def _execute():
        # 1. Fetch Campaign and Set Initial RUNNING State
        campaign = await SocialCampaign.objects.aget(id=campaign_id)
        campaign.status = "RUNNING"
        await campaign.asave()

        # 2. Initialize Checkpointer
        postgres_url = getattr(settings, "POSTGRES_POOL_URL", None) or os.environ.get("POSTGRES_POOL_URL")
        checkpointer = await get_postgres_checkpointer(conn_string=postgres_url)

        # 3. Assemble and Compile Graph
        graph = create_social_agent_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": campaign.langgraph_thread_id}}

        initial_state = {
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
            "hitl_payload": {"required": False, "approved": None},
            "published_post_ids": {},
            "error_logs": [],
            "execution_history": []
        }

        # 4. Stream Graph Execution and Handle Interrupts
        try:
            async for event in graph.astream(initial_state, config=config, stream_mode="values"):
                pass
        except Exception as stream_err:
            logger.error("Graph streaming execution error on campaign '%s': %s", campaign_id, stream_err, exc_info=True)

        # 5. Check if Interrupted at HITL Gate
        state_snapshot = graph.get_state(config)
        if state_snapshot.next and "hitl_gate" in state_snapshot.next:
            logger.info("Campaign '%s' paused at HITL approval gate.", campaign_id)
            campaign.status = "AWAITING_APPROVAL"
            await campaign.asave()
            return "PAUSED_AT_HITL"

        # 6. Workflow Completed (Published or Aborted)
        final_state = state_snapshot.values if hasattr(state_snapshot, "values") else {}
        published_ids = final_state.get("published_post_ids", {})
        drafts = final_state.get("draft_posts", {})
        eval_report = final_state.get("audit_evaluation")

        if eval_report:
            campaign.overall_quality_score = eval_report.overall_quality_score
            campaign.safety_passed = eval_report.is_safe

        if published_ids:
            campaign.status = "PUBLISHED"
            for platform, post_data in drafts.items():
                content = post_data.content if hasattr(post_data, "content") else str(post_data.get("content", ""))
                media_urls = post_data.media_urls if hasattr(post_data, "media_urls") else post_data.get("media_urls", [])
                alt_text = post_data.alt_text if hasattr(post_data, "alt_text") else post_data.get("alt_text")
                ext_id = published_ids.get(platform)

                await SocialPost.objects.acreate(
                    campaign=campaign,
                    platform=platform,
                    post_text=content,
                    media_urls=media_urls,
                    alt_text=alt_text,
                    external_post_id=ext_id,
                    character_count=len(content)
                )
        else:
            campaign.status = "FAILED"

        await campaign.asave()
        logger.info("Campaign '%s' completed with final status '%s'", campaign_id, campaign.status)
        return campaign.status

    return asyncio.run(_execute())


@shared_task(bind=True, max_retries=2)
def resume_hitl_workflow_task(
    self,
    campaign_id: str,
    approved: bool,
    reviewer_notes: str,
    modified_content: dict
):
    """
    Resumes an interrupted workflow thread by passing a signed Command(resume=...) payload.

    Args:
        campaign_id: UUID of the SocialCampaign.
        approved: True if approved, False if rejected.
        reviewer_notes: Optional audit notes.
        modified_content: Optional dictionary of edited post copy per platform.
    """
    logger.info("Celery task started: resume_hitl_workflow_task for campaign '%s' [Approved: %s]", campaign_id, approved)

    async def _resume():
        campaign = await SocialCampaign.objects.aget(id=campaign_id)
        postgres_url = getattr(settings, "POSTGRES_POOL_URL", None) or os.environ.get("POSTGRES_POOL_URL")
        checkpointer = await get_postgres_checkpointer(conn_string=postgres_url)

        graph = create_social_agent_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": campaign.langgraph_thread_id}}

        resume_payload = {
            "approved": approved,
            "reviewer_notes": reviewer_notes,
            "modified_content": modified_content or {}
        }

        # Dispatch resumption Command to wake the interrupted node
        async for event in graph.astream(Command(resume=resume_payload), config=config, stream_mode="values"):
            pass

        state_snapshot = graph.get_state(config)
        final_state = state_snapshot.values if hasattr(state_snapshot, "values") else {}
        published_ids = final_state.get("published_post_ids", {})
        drafts = final_state.get("draft_posts", {})

        if approved and published_ids:
            campaign.status = "PUBLISHED"
            for platform, post_data in drafts.items():
                content = post_data.content if hasattr(post_data, "content") else str(post_data.get("content", ""))
                media_urls = post_data.media_urls if hasattr(post_data, "media_urls") else post_data.get("media_urls", [])
                alt_text = post_data.alt_text if hasattr(post_data, "alt_text") else post_data.get("alt_text")
                ext_id = published_ids.get(platform)

                await SocialPost.objects.acreate(
                    campaign=campaign,
                    platform=platform,
                    post_text=content,
                    media_urls=media_urls,
                    alt_text=alt_text,
                    external_post_id=ext_id,
                    character_count=len(content)
                )
        else:
            campaign.status = "REJECTED"

        await campaign.asave()
        logger.info("Resumed campaign '%s' finalized with status '%s'", campaign_id, campaign.status)
        return campaign.status

    return asyncio.run(_resume())