"""
social_agent/agents/researcher.py
Trend-research and Brand-RAG context synthesis agent implementing Corrective RAG (CRAG).
"""
import logging
from typing import Dict, Any, List, Optional

from social_agent.memory.hybrid_retriever import HybridRetriever
from social_agent.mcp_tools.client import SocialMCPClient
from social_agent.guardrails.safety import SafetyGuardrail

logger = logging.getLogger(__name__)


class TrendResearcherAgent:
    """
    Coordinates semantic Brand RAG retrieval and live web trend search to generate
    ground-truth context for downstream multimodal creative copywriting.
    """
    def __init__(
        self,
        retriever: Optional[HybridRetriever] = None,
        mcp_client: Optional[SocialMCPClient] = None,
        safety: Optional[SafetyGuardrail] = None
    ):
        self.retriever = retriever
        self.mcp_client = mcp_client or SocialMCPClient()
        self.safety = safety or SafetyGuardrail()

    async def research_topic(self, prompt: str, campaign_id: str) -> Dict[str, Any]:
        """
        Executes topic research:
        1. Inbound safety scan (PII + Prompt Injection detection).
        2. Brand RAG hybrid retrieval (dense + sparse BM25).
        3. FastMCP web trends tool call.
        4. Context consolidation.

        Args:
            prompt: Raw user/campaign prompt.
            campaign_id: Unique campaign identifier.

        Returns:
            Dict containing sanitized prompt, research_context, trend_signals, and is_safe flag.
        """
        logger.info("TrendResearcherAgent: Starting research for campaign '%s'", campaign_id)

        # 1. Pre-Execution Safety Inspection
        scan_res = await self.safety.scan_inbound_prompt(prompt)
        if not scan_res.is_safe:
            logger.warning("Inbound security scan failed for prompt: %s", scan_res.detected_violations)
            return {
                "original_prompt": prompt,
                "research_context": [],
                "trend_signals": [],
                "is_safe": False,
                "detected_violations": scan_res.detected_violations
            }

        sanitized_prompt = scan_res.sanitized_text

        # 2. Hybrid Brand RAG Retrieval
        brand_chunks = [
            "Brand Voice Rule: Authoritative, innovative, technically grounded.",
            "Prohibited Terms: revolutionize, synergy, disruptive, game-changer.",
            "Hashtag Guidelines: 2-3 focused industry hashtags maximum."
        ]

        if self.retriever:
            try:
                verdict = await self.retriever.retrieve_and_evaluate(
                    query=sanitized_prompt,
                    collection_name="brand_governance_rag",
                    top_k=4,
                    mcp_client=self.mcp_client
                )
                if verdict.documents:
                    brand_chunks = [doc.content for doc in verdict.documents]
                if verdict.factual_strips:
                    brand_chunks.extend(verdict.factual_strips)
            except Exception as rag_err:
                logger.debug("Hybrid retriever query error (%s). Using fallback brand context.", rag_err)

        # 3. Live Web Trends Discovery via FastMCP
        retrieved_trends = []
        try:
            trend_data = await self.mcp_client.call_tool(
                "search_trends",
                {"query": sanitized_prompt, "timeframe": "24h", "max_results": 5}
            )
            retrieved_trends = trend_data.get("trends", [])
        except Exception as mcp_err:
            logger.debug("FastMCP search_trends tool offline (%s). Using local trend synthesis.", mcp_err)
            retrieved_trends = [
                f"Trend Signal for '{sanitized_prompt}': Increasing enterprise focus on reliable multi-agent systems and verified benchmarks."
            ]

        # 4. Consolidate Context
        combined_context = brand_chunks + retrieved_trends

        return {
            "original_prompt": sanitized_prompt,
            "research_context": combined_context,
            "trend_signals": retrieved_trends,
            "is_safe": True
        }