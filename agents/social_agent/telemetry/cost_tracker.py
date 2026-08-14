"""
social_agent/telemetry/cost_tracker.py
Token usage accounting, per-model cost estimation, latency benchmarking, and budget cap guardrails.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("social_agent.telemetry")


class TokenUsageRecord(BaseModel):
    """Granular execution record of token expenditure and latency for an individual node."""
    campaign_id: str = Field(..., description="Target campaign identifier.")
    node_name: str = Field(..., description="Graph node name.")
    model_name: str = Field(..., description="LLM identifier.")
    prompt_tokens: int = Field(default=0, ge=0, description="Input prompt tokens.")
    completion_tokens: int = Field(default=0, ge=0, description="Output completion tokens.")
    total_tokens: int = Field(default=0, ge=0, description="Total tokens consumed.")
    cost_usd: float = Field(default=0.0, ge=0.0, description="Estimated dollar cost.")
    latency_seconds: float = Field(default=0.0, ge=0.0, description="Execution duration in seconds.")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CampaignCostSummary(BaseModel):
    """Aggregated resource usage, financial cost, and SLA report for an entire campaign."""
    campaign_id: str = Field(..., description="Campaign identifier.")
    total_prompt_tokens: int = Field(default=0)
    total_completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    total_cost_usd: float = Field(default=0.0)
    total_duration_seconds: float = Field(default=0.0)
    node_breakdown: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    budget_exceeded: bool = Field(default=False)


class CostTracker:
    """
    Per-request token counter, cost estimator, latency profiler, and budget circuit breaker.
    Enforces $25.00 daily cost cap and 16,000 tokens per-campaign budget.
    """
    # Pricing rates per 1,000 tokens
    PRICING_TABLE: Dict[str, Dict[str, Dict[str, float]]] = {
        "llama3.3:70b-instruct": {
            "local": {"prompt": 0.0, "completion": 0.0},
            "cloud": {"prompt": 0.0030, "completion": 0.0060}
        },
        "qwen2.5:32b-instruct": {
            "local": {"prompt": 0.0, "completion": 0.0},
            "cloud": {"prompt": 0.0015, "completion": 0.0030}
        },
        "llama3.2:11b-vision": {
            "local": {"prompt": 0.0, "completion": 0.0},
            "cloud": {"prompt": 0.0010, "completion": 0.0020}
        },
        "mistral-small:24b": {
            "local": {"prompt": 0.0, "completion": 0.0},
            "cloud": {"prompt": 0.0010, "completion": 0.0020}
        }
    }

    def __init__(
        self,
        daily_cost_cap_usd: float = 25.0,
        campaign_token_budget: int = 16000
    ):
        self.daily_cost_cap_usd = daily_cost_cap_usd
        self.campaign_token_budget = campaign_token_budget
        
        # In-memory storage: {campaign_id: [TokenUsageRecord, ...]}
        self._campaigns: Dict[str, List[TokenUsageRecord]] = {}
        self._daily_total_cost: float = 0.0
        self._buffer: List[TokenUsageRecord] = []

    def _estimate_tokens(self, text: str) -> int:
        """Fallback token estimator (~4 characters per token)."""
        if not text:
            return 0
        return max(1, len(text) // 4)

    def record_step_usage(
        self,
        campaign_id: str,
        node_name: str,
        model_name: str,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        latency_seconds: float = 0.0,
        is_cloud_fallback: bool = False
    ) -> TokenUsageRecord:
        """
        Calculates cost, records step latency and token consumption, and appends to campaign history.

        Args:
            campaign_id: Campaign UUID.
            node_name: Name of the executed graph node.
            model_name: Model identifier string.
            prompt_tokens: Prompt token count.
            completion_tokens: Completion token count.
            latency_seconds: Duration in seconds.
            is_cloud_fallback: Whether cloud rates apply.

        Returns:
            Validated TokenUsageRecord.
        """
        p_tok = prompt_tokens if prompt_tokens is not None else 0
        c_tok = completion_tokens if completion_tokens is not None else 0
        tot_tok = p_tok + c_tok

        # Calculate unit cost
        tier = "cloud" if is_cloud_fallback else "local"
        rates = self.PRICING_TABLE.get(model_name, self.PRICING_TABLE["llama3.3:70b-instruct"])[tier]
        cost = (p_tok / 1000.0 * rates["prompt"]) + (c_tok / 1000.0 * rates["completion"])
        cost = round(cost, 6)

        record = TokenUsageRecord(
            campaign_id=campaign_id,
            node_name=node_name,
            model_name=model_name,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            total_tokens=tot_tok,
            cost_usd=cost,
            latency_seconds=round(latency_seconds, 3)
        )

        if campaign_id not in self._campaigns:
            self._campaigns[campaign_id] = []
        self._campaigns[campaign_id].append(record)

        self._daily_total_cost += cost
        self._buffer.append(record)

        # Ring buffer eviction: drop oldest if buffer exceeds 1,000 entries
        if len(self._buffer) > 1000:
            self._buffer.pop(0)

        # Non-blocking attempt to write to Django AgentAuditLog if in Django context
        try:
            from social_agent.models import AgentAuditLog
            AgentAuditLog.objects.create(
                campaign_id=campaign_id,
                node_name=node_name,
                agent_name=f"Agent_{node_name}",
                input_state_summary=f"Tokens: {p_tok} prompt / {c_tok} compl",
                output_state_summary=f"Cost: ${cost:.6f} | Latency: {latency_seconds:.2f}s",
                execution_time_seconds=latency_seconds,
                token_usage=record.dict()
            )
        except Exception as e:
            logger.debug("Audit log database write bypassed: %s", e)

        return record

    def get_campaign_summary(self, campaign_id: str) -> CampaignCostSummary:
        """
        Aggregates token consumption, financial cost, and latency metrics across all nodes for a campaign.
        """
        records = self._campaigns.get(campaign_id, [])
        total_p = sum(r.prompt_tokens for r in records)
        total_c = sum(r.completion_tokens for r in records)
        total_tok = total_p + total_c
        total_cost = round(sum(r.cost_usd for r in records), 6)
        total_duration = round(sum(r.latency_seconds for r in records), 3)

        # Node-by-node aggregation
        node_breakdown: Dict[str, Dict[str, Any]] = {}
        for r in records:
            if r.node_name not in node_breakdown:
                node_breakdown[r.node_name] = {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "latency_seconds": 0.0
                }
            node_breakdown[r.node_name]["calls"] += 1
            node_breakdown[r.node_name]["prompt_tokens"] += r.prompt_tokens
            node_breakdown[r.node_name]["completion_tokens"] += r.completion_tokens
            node_breakdown[r.node_name]["total_tokens"] += r.total_tokens
            node_breakdown[r.node_name]["cost_usd"] = round(node_breakdown[r.node_name]["cost_usd"] + r.cost_usd, 6)
            node_breakdown[r.node_name]["latency_seconds"] = round(node_breakdown[r.node_name]["latency_seconds"] + r.latency_seconds, 3)

        budget_exceeded = (total_tok > self.campaign_token_budget) or (self._daily_total_cost > self.daily_cost_cap_usd)
        if budget_exceeded:
            logger.warning(
                "Budget threshold exceeded on campaign '%s': %d/%d tokens | Daily Cost: $%.2f/$%.2f",
                campaign_id, total_tok, self.campaign_token_budget, self._daily_total_cost, self.daily_cost_cap_usd
            )

        return CampaignCostSummary(
            campaign_id=campaign_id,
            total_prompt_tokens=total_p,
            total_completion_tokens=total_c,
            total_tokens=total_tok,
            total_cost_usd=total_cost,
            total_duration_seconds=total_duration,
            node_breakdown=node_breakdown,
            budget_exceeded=budget_exceeded
        )

    def check_budget_clearance(self, campaign_id: str, estimated_tokens: int = 1000) -> bool:
        """
        Circuit breaker test: verifies whether a prospective node call remains within budget limits.
        """
        records = self._campaigns.get(campaign_id, [])
        current_tokens = sum(r.total_tokens for r in records)

        if (current_tokens + estimated_tokens) > self.campaign_token_budget:
            logger.warning(
                "Campaign token budget circuit breaker tripped (%d + %d > %d)",
                current_tokens, estimated_tokens, self.campaign_token_budget
            )
            return False

        if self._daily_total_cost >= self.daily_cost_cap_usd:
            logger.warning(
                "Daily cost cap circuit breaker tripped ($%.2f >= $%.2f)",
                self._daily_total_cost, self.daily_cost_cap_usd
            )
            return False

        return True

    def reset_daily_accumulator(self) -> None:
        """Resets the rolling daily cost accumulator (scheduled via Celery Beat)."""
        logger.info("Resetting daily cost accumulator (Previous total: $%.4f)", self._daily_total_cost)
        self._daily_total_cost = 0.0
        self._buffer.clear()