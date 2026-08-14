"""
social_agent/agents/__init__.py
Unified package exports for the multi-agent roster and LLM factory.
Sets dummy OPENAI_API_KEY to satisfy CrewAI initialization requirements.
"""
import os

# Set dummy API key to satisfy CrewAI startup validation when running local Ollama models
if not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = "NA"

from .llm_factory import get_chat_model
from .researcher import TrendResearcherAgent
from .copywriter import CopywritingCrew
from .media_specialist import MediaSpecialistAgent
from .auditor import ComplianceAuditorAgent
from .publisher import SocialPublisherAgent

__all__ = [
    "get_chat_model",
    "TrendResearcherAgent",
    "CopywritingCrew",
    "MediaSpecialistAgent",
    "ComplianceAuditorAgent",
    "SocialPublisherAgent",
]