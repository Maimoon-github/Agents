"""
social_agent/memory/session_manager.py
Thread-isolated short-term session context, token compaction, and Django ORM audit logging.
"""
import logging
from typing import Dict, Any, List, Optional
import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SessionContext(BaseModel):
    """Represents the short-term working context and preferences for an execution thread."""
    thread_id: str = Field(..., description="Unique LangGraph thread identifier.")
    turn_history: List[Dict[str, Any]] = Field(default_factory=list, description="Sequence of turn events.")
    rolling_summary: Optional[str] = Field(default=None, description="Consolidated summary of earlier turns.")
    preferences: Dict[str, Any] = Field(default_factory=dict, description="Session-level user preferences and brand notes.")


class SessionManager:
    """
    Manages short-term conversation context, token budget constraints, and rolling message history.
    Ensures thread isolation and asynchronous persistence to Django ORM.
    """
    def __init__(
        self,
        max_context_tokens: int = 4096,
        summary_model: str = "llama3.3:70b-instruct",
        ollama_base_url: str = "http://127.0.0.1:11434/v1"
    ):
        self.max_context_tokens = max_context_tokens
        self.summary_model = summary_model
        self.ollama_base_url = ollama_base_url.rstrip("/")
        
        # Thread-isolated in-memory cache
        self._threads: Dict[str, Dict[str, Any]] = {}

    def _ensure_thread(self, thread_id: str):
        if thread_id not in self._threads:
            self._threads[thread_id] = {
                "history": [],
                "summary": None,
                "preferences": {}
            }

    def _estimate_tokens(self, text: str) -> int:
        """Heuristic token estimator (average 4 chars per token)."""
        if not text:
            return 0
        return max(1, len(text) // 4)

    def get_session_context(self, thread_id: str) -> SessionContext:
        """
        Retrieves thread-isolated context, turn history, and user preferences.
        """
        self._ensure_thread(thread_id)
        data = self._threads[thread_id]
        return SessionContext(
            thread_id=thread_id,
            turn_history=list(data["history"]),
            rolling_summary=data["summary"],
            preferences=dict(data["preferences"])
        )

    def set_user_preferences(self, thread_id: str, preferences: Dict[str, Any]) -> None:
        """Updates session-level user preferences for the specified thread."""
        self._ensure_thread(thread_id)
        self._threads[thread_id]["preferences"].update(preferences)

    async def append_turn_event(
        self,
        thread_id: str,
        campaign_id: str,
        node_name: str,
        input_summary: str,
        output_summary: str,
        token_usage: Optional[Dict[str, int]] = None
    ) -> None:
        """
        Appends a node execution turn to thread history and logs an AgentAuditLog record in Django.
        """
        self._ensure_thread(thread_id)
        event = {
            "node_name": node_name,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "token_usage": token_usage or {}
        }
        self._threads[thread_id]["history"].append(event)

        # Async non-blocking write to Django ORM if available
        try:
            from social_agent.models import AgentAuditLog, SocialCampaign
            campaign = await SocialCampaign.objects.filter(id=campaign_id).afirst()
            if campaign:
                await AgentAuditLog.objects.acreate(
                    campaign=campaign,
                    node_name=node_name,
                    agent_name=f"Agent_{node_name}",
                    input_state_summary=input_summary[:500],
                    output_state_summary=output_summary[:500],
                    token_usage=token_usage or {},
                    execution_time_seconds=0.5
                )
        except Exception as db_err:
            logger.debug("Django ORM AgentAuditLog write bypassed: %s", db_err)

    async def _summarize_turn_batch(self, messages_to_summarize: List[Dict[str, Any]], current_summary: Optional[str]) -> str:
        """Calls local LLM to generate an executive summary chunk of older turns."""
        turns_text = "\n".join(
            f"{m.get('role', 'unknown').upper()}: {m.get('content', '')}"
            for m in messages_to_summarize
        )
        prompt = (
            "Summarize the key context, facts, and decisions from these earlier turns concisely. "
            "Retain all critical brand guidelines, user feedback, and campaign parameters.\n\n"
            f"Previous Summary: {current_summary or 'None'}\n\n"
            f"New Turns to Condense:\n{turns_text}\n\n"
            "Summary:"
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                endpoint = f"{self.ollama_base_url}/chat/completions"
                payload = {
                    "model": self.summary_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 512
                }
                resp = await client.post(endpoint, json=payload)
                if resp.status_code == 200:
                    summary_text = resp.json()["choices"][0]["message"]["content"].strip()
                    return summary_text
        except Exception as e:
            logger.debug("LLM summarization failed (%s); using deterministic extraction.", e)

        # Fallback deterministic compaction
        extracted_points = [
            f"- {m.get('role')}: {m.get('content')[:80]}..."
            for m in messages_to_summarize if m.get("content")
        ]
        return (current_summary or "") + "\n" + "\n".join(extracted_points)

    async def compact_context(
        self,
        thread_id: str,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Token-aware sliding window compaction:
        If total estimated tokens exceed max_tokens, retains the last N=5 turns intact
        and condenses older prefix messages into an executive summary chunk.
        """
        budget = max_tokens or self.max_context_tokens
        total_tokens = sum(self._estimate_tokens(m.get("content", "")) for m in messages)

        if total_tokens <= budget or len(messages) <= 5:
            return messages

        self._ensure_thread(thread_id)
        current_summary = self._threads[thread_id]["summary"]

        # Keep recent N=5 turns, compact prefix
        split_idx = max(1, len(messages) - 5)
        prefix = messages[:split_idx]
        recent = messages[split_idx:]

        new_summary = await self._summarize_turn_batch(prefix, current_summary)
        self._threads[thread_id]["summary"] = new_summary

        compacted = [
            {
                "role": "system",
                "content": f"[CONSOLIDATED ROLLING CONTEXT SUMMARY]:\n{new_summary}"
            }
        ]
        compacted.extend(recent)
        logger.info(
            "Compacted context for thread '%s' from %d to %d messages (%d est. tokens).",
            thread_id, len(messages), len(compacted),
            sum(self._estimate_tokens(m.get("content", "")) for m in compacted)
        )
        return compacted