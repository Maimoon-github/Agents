"""
social_agent/agents/copywriter.py
CrewAI-compatible multi-platform creative copywriting crew with platform specialization and remediation injection.
"""
import re
import logging
from typing import Dict, Any, List, Optional

try:
    from langchain_core.messages import SystemMessage, HumanMessage
except ImportError:
    class SystemMessage:
        def __init__(self, content: str): self.content = content
    class HumanMessage:
        def __init__(self, content: str): self.content = content

from social_agent.graph.state import PlatformPostPayload
from social_agent.agents.llm_factory import get_chat_model

logger = logging.getLogger(__name__)


class CopywritingCrew:
    """
    Orchestrates specialized copywriting personas for X (Twitter), Instagram, and TikTok.
    Enforces channel-specific character bounds, hashtag limits, and remediation feedback.
    """
    def __init__(self, llm_model: Optional[Any] = None):
        self.llm = llm_model or get_chat_model("copywriter")

    def _get_platform_system_prompt(self, platform: str, context: str, feedback: Optional[str] = None) -> str:
        """Constructs role-specific prompt instructions per social channel."""
        remediation_text = (
            f"\n\nCRITICAL AUDIT REMEDIATION FEEDBACK:\n{feedback}\n"
            "You MUST resolve all issues mentioned above and eliminate all prohibited buzzwords.\n"
            if feedback else ""
        )

        base_rules = (
            f"Brand Ground Truth & Guidelines:\n{context}\n"
            f"{remediation_text}"
        )

        if platform == "x_twitter":
            return (
                "You are an Elite X (Twitter) Technical Copywriter.\n"
                f"{base_rules}\n"
                "Constraints:\n"
                "- Write a single, highly engaging tweet strictly UNDER 280 characters.\n"
                "- Tone: Authoritative, punchy, technically grounded.\n"
                "- Include 1-2 focused hashtags (e.g. #AI #Architecture).\n"
                "- Output ONLY the final tweet text. No preamble or quotes."
            )
        elif platform == "instagram":
            return (
                "You are a Senior Instagram Visual Storyteller.\n"
                f"{base_rules}\n"
                "Constraints:\n"
                "- Write an informative, engaging post caption with a strong hook.\n"
                "- Structure: 1. Hook -> 2. Key Architecture Takeaways -> 3. Call to Action.\n"
                "- Length: 300 to 1200 characters (max 2200).\n"
                "- Include 3-5 relevant hashtags at the bottom.\n"
                "- Output ONLY the final caption text."
            )
        elif platform == "tiktok":
            return (
                "You are a Viral TikTok Content Strategist.\n"
                f"{base_rules}\n"
                "Constraints:\n"
                "- Write a short, high-energy video caption with a strong 3-second hook.\n"
                "- Length: 100 to 500 characters.\n"
                "- Include trending niche tags.\n"
                "- Output ONLY the caption text."
            )
        return f"You are a Social Media Copywriter.\n{base_rules}\nOutput the final post text."

    async def generate_platform_drafts(
        self,
        prompt: str,
        platforms: List[str],
        context: List[str],
        remediation_feedback: Optional[str] = None
    ) -> Dict[str, PlatformPostPayload]:
        """
        Generates platform-tailored post drafts for all requested social channels.

        Args:
            prompt: Original campaign objective.
            platforms: List of target platforms ('x_twitter', 'instagram', 'tiktok').
            context: Synthesized brand guidelines and web trends.
            remediation_feedback: Optional critique from previous evaluation failure.

        Returns:
            Dict mapping platform name to validated PlatformPostPayload.
        """
        context_str = "\n".join(f"- {c}" for c in context)
        drafts: Dict[str, PlatformPostPayload] = {}

        for platform in platforms:
            sys_prompt = self._get_platform_system_prompt(platform, context_str, remediation_feedback)
            user_prompt = f"Write the social media post for this campaign topic: {prompt}"

            try:
                response = await self.llm.ainvoke([
                    SystemMessage(content=sys_prompt),
                    HumanMessage(content=user_prompt)
                ])
                raw_text = response.content.strip().strip('"').strip("'")
            except Exception as e:
                logger.warning("LLM drafting failed for %s (%s). Using fallback template.", platform, e)
                raw_text = f"Architectural Milestone for {prompt[:80]}: Building resilient multi-agent systems with verified SLAs. #AI #Architecture"

            # Post-processing: extract hashtags and media URLs
            hashtags = re.findall(r"#\w+", raw_text)
            if not hashtags:
                hashtags = ["#AIArchitecture", "#EnterpriseAI"]

            # Enforce X character limit truncation fallback if LLM slightly exceeded
            if platform == "x_twitter" and len(raw_text) > 280:
                raw_text = raw_text[:270].rsplit(" ", 1)[0] + " #AI"

            drafts[platform] = PlatformPostPayload(
                platform=platform,
                content=raw_text,
                hashtags=hashtags[:5],
                media_urls=["https://storage.cdn.internal/assets/architecture_diagram_2026.png"],
                character_count=len(raw_text)
            )

        logger.info("CopywritingCrew generated %d platform drafts: %s", len(drafts), list(drafts.keys()))
        return drafts