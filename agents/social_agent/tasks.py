"""
social_agent/tasks.py
Celery background worker executing the async compiled graph.
"""
from celery import shared_task
import asyncio
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from django.conf import settings
from social_agent.models import SocialCampaign, AgentAuditLog, SocialPost
from social_agent.graph.workflow import create_social_agent_graph


@shared_task(bind=True, max_retries=2)
def run_campaign_workflow_task(self, campaign_id: str):
    """
    Executes or resumes a campaign workflow inside an isolated AsyncIO loop.
    """
    async def _execute():
        campaign = await SocialCampaign.objects.aget(id=campaign_id)
        campaign.status = 'RUNNING'
        await campaign.asave()
        
        db_uri = settings.DATABASES['default']['POSTGRES_POOL_URL']
        
        async with AsyncConnectionPool(conninfo=db_uri, max_size=5) as pool:
            checkpointer = AsyncPostgresSaver(pool)
            await checkpointer.setup()
            
            graph = create_social_agent_graph().compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": campaign.langgraph_thread_id}}
            
            # Initial state setup
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
                "hitl_payload": {"required": True, "approved": None},
                "published_post_ids": {},
                "error_logs": [],
                "execution_history": []
            }
            
            async for event in graph.astream(initial_state, config=config):
                # Check for interruption (HITL Pause)
                state_snapshot = await graph.aget_state(config)
                if state_snapshot.next and "hitl_gate" in state_snapshot.next:
                    campaign.status = 'AWAITING_APPROVAL'
                    await campaign.asave()
                    return "PAUSED_AT_HITL"
            
            # If completed without pause or after resume
            final_state = await graph.aget_state(config)
            if final_state.values.get("published_post_ids"):
                campaign.status = 'PUBLISHED'
                for platform, post_data in final_state.values["draft_posts"].items():
                    await SocialPost.objects.acreate(
                        campaign=campaign,
                        platform=platform,
                        post_text=post_data.content,
                        media_urls=post_data.media_urls,
                        alt_text=post_data.alt_text,
                        external_post_id=final_state.values["published_post_ids"].get(platform),
                        character_count=post_data.character_count
                    )
            else:
                campaign.status = 'REJECTED'
                
            await campaign.asave()
            return "COMPLETED"

    return asyncio.run(_execute())


@shared_task
def resume_hitl_workflow_task(campaign_id: str, approved: bool, reviewer_notes: str, modified_content: dict):
    """
    Resumes an interrupted workflow by passing a Command payload to the thread.
    """
    async def _resume():
        campaign = await SocialCampaign.objects.aget(id=campaign_id)
        db_uri = settings.DATABASES['default']['POSTGRES_POOL_URL']
        
        async with AsyncConnectionPool(conninfo=db_uri, max_size=5) as pool:
            checkpointer = AsyncPostgresSaver(pool)
            graph = create_social_agent_graph().compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": campaign.langgraph_thread_id}}
            
            resume_payload = {
                "approved": approved,
                "reviewer_notes": reviewer_notes,
                "modified_content": modified_content
            }
            
            # Pass Command(resume=...) to wake up the interrupted node
            async for _ in graph.astream(Command(resume=resume_payload), config=config):
                pass
                
            campaign.status = 'PUBLISHED' if approved else 'REJECTED'
            await campaign.asave()
            
    return asyncio.run(_resume())