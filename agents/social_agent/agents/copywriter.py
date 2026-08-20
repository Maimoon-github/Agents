"""
social_agent/agents/copywriter.py
CrewAI v1.15+ compatible multi-platform creative copywriting sub-crew.
Enforces specialized agent delegation, bounded tasks, and strict Pydantic outputs.
"""
import logging
from typing import Dict, Any, List, Optional
try:
    from crewai import Agent, Task, Crew, Process
except ImportError:
    # Fail-safe mocks for environments lacking crewai binaries
    pass

from social_agent.graph.state import PlatformPostPayload
from social_agent.agents.llm_factory import get_chat_model

logger = logging.getLogger(__name__)

class CopywritingCrew:
    """
    CrewAI Orchestrator: Delegates campaign drafting to specialized Platform Copywriter agents.
    Outputs are guaranteed to construct valid PlatformPostPayload dicts.
    """
    def __init__(self, llm_model: Optional[Any] = None):
        self.llm = llm_model or get_chat_model("copywriter")

    def _create_agents(self) -> Dict[str, Any]:
        """Defines the micro-tier specialized agents."""
        logger.info("CrewAI: Initializing strategic and platform copywriter agents.")
        try:
            lead_strategist = Agent(
                role="Lead Social Strategist",
                goal="Deconstruct brand context into targeted platform directives and viral hooks.",
                backstory="You are an award-winning strategist guiding a multi-platform content syndicate.",
                llm=self.llm,
                verbose=False, max_iter=3, max_rpm=30, respect_context_window=True
            )
            
            x_writer = Agent(
                role="X (Twitter) Copywriter",
                goal="Craft highly technical, concise, authoritative micro-copy under 280 characters.",
                backstory="A battle-tested tech Twitter ghostwriter who achieves extreme impact in few words.",
                llm=self.llm,
                verbose=False, max_iter=3, max_rpm=30, respect_context_window=True
            )
            
            instagram_writer = Agent(
                role="Instagram Storyteller",
                goal="Draft visually evocative, structured captions culminating in engagement hooks.",
                backstory="A master of visual storytelling and spacing, driving strong community engagement.",
                llm=self.llm,
                verbose=False, max_iter=3, max_rpm=30, respect_context_window=True
            )
            
            tiktok_writer = Agent(
                role="TikTok Scripter",
                goal="Generate high-energy, relatable, fast-paced short-form video hooks.",
                backstory="A Gen-Z trend expert producing viral hooks for tech and education audiences.",
                llm=self.llm,
                verbose=False, max_iter=3, max_rpm=30, respect_context_window=True
            )
            
            return {
                "strategist": lead_strategist,
                "x_twitter": x_writer,
                "instagram": instagram_writer,
                "tiktok": tiktok_writer
            }
        except NameError:
            # Fallback for absent CrewAI package
            return {}

    async def generate_platform_drafts(
        self,
        prompt: str,
        platforms: List[str],
        context: List[str],
        remediation_feedback: Optional[str] = None
    ) -> Dict[str, PlatformPostPayload]:
        logger.info("CrewAI: Bootstrapping multi-agent copy generation for %s", platforms)
        
        context_str = "\n".join(f"- {c}" for c in context)
        remediation_block = (
            f"\n\nCRITICAL AUDITOR FEEDBACK (MUST FIX):\n{remediation_feedback}"
            if remediation_feedback else ""
        )

        agents = self._create_agents()
        if not agents:
            logger.warning("CrewAI missing: Falling back to mocked payloads.")
            return self._fallback_generation(prompt, platforms)
            
        tasks = []
        platform_mapping = []

        # Build dynamic tasks mapped to explicit Pydantic schemas per platform
        for plat in platforms:
            if plat not in agents:
                continue
                
            task_desc = (
                f"Draft a viral {plat} post based on the campaign objective: '{prompt}'.\n"
                f"Apply these brand rules: {context_str}{remediation_block}"
            )
            
            try:
                task = Task(
                    description=task_desc,
                    expected_output=f"A final {plat} copy payload strictly matching PlatformPostPayload schema.",
                    agent=agents[plat],
                    output_pydantic=PlatformPostPayload
                )
                tasks.append(task)
                platform_mapping.append(plat)
            except NameError:
                pass

        drafts: Dict[str, PlatformPostPayload] = {}

        if tasks:
            try:
                crew = Crew(
                    agents=[agents["strategist"]] + [agents[p] for p in platforms if p in agents],
                    tasks=tasks,
                    process=Process.sequential,
                    verbose=False, max_iter=3, max_rpm=30, respect_context_window=True
                )
                # Ensure asyncio doesn't clash with sync kickoff
                import asyncio
                crew_output = await asyncio.to_thread(crew.kickoff)
                
                # Match output tasks to platforms
                for p_name, t_obj in zip(platform_mapping, crew.tasks):
                    if t_obj.output and t_obj.output.pydantic:
                        payload = t_obj.output.pydantic
                        # Overwrite specific generic mappings
                        payload.platform = p_name
                        payload.character_count = len(payload.content)
                        drafts[p_name] = payload
            except Exception as e:
                logger.error("CrewAI kickoff failed: %s", e)
                return self._fallback_generation(prompt, platforms)
        
        return drafts

    def _fallback_generation(self, prompt: str, platforms: List[str]) -> Dict[str, PlatformPostPayload]:
        drafts = {}
        for plat in platforms:
            drafts[plat] = PlatformPostPayload(
                platform=plat,
                content=f"Fallback generated draft for {plat}: {prompt[:50]}...",
                character_count=50
            )
        return drafts
