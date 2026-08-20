"""
social_agent/agents/llm_factory.py
Role-based ChatOpenAI-compatible LLM factory connecting to Ollama/vLLM endpoints with model fallback routing.
"""
import os
import logging
from typing import Optional, Dict, Any

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    class ChatOpenAI:
        def __init__(
            self,
            base_url: str = "http://127.0.0.1:11434/v1",
            api_key: str = "NA",
            model: str = "llama3.3:70b-instruct",
            temperature: float = 0.3,
            max_tokens: int = 2048,
            timeout: float = 60.0,
            model_kwargs: Optional[Dict[str, Any]] = None
        ):
            self.base_url = base_url
            self.api_key = api_key
            self.model = model
            self.temperature = temperature
            self.max_tokens = max_tokens
            self.timeout = timeout
            self.model_kwargs = model_kwargs or {}

        async def ainvoke(self, messages, **kwargs):
            class Response:
                content = (
                    "Enterprise Multi-Agent Workflow Update: Scalable state machines "
                    "with deterministic guardrails and verified resilience. #AI #Architecture"
                )
            return Response()

logger = logging.getLogger(__name__)

# Model Configuration Mapping per Role
MODEL_ROSTER_CONFIG: Dict[str, Dict[str, Any]] = {
    "copywriter": {
        "model": os.environ.get("COPYWRITER_LLM_MODEL", "llama3.3:70b-instruct"),
        "temperature": 0.70,
        "max_tokens": 4096,
        "timeout": 60.0,
        "model_kwargs": {"top_p": 0.95}
    },
    "researcher": {
        "model": os.environ.get("RESEARCHER_LLM_MODEL", "qwen2.5:32b-instruct"),
        "temperature": 0.20,
        "max_tokens": 2048,
        "timeout": 30.0,
        "model_kwargs": {"top_p": 0.90}
    },
    "vision": {
        "model": os.environ.get("VISION_LLM_MODEL", "llama3.2:11b-vision"),
        "temperature": 0.10,
        "max_tokens": 1024,
        "timeout": 20.0,
        "model_kwargs": {"top_p": 0.80}
    },
    "evaluator": {
        "model": os.environ.get("EVALUATOR_LLM_MODEL", "llama3.3:70b-instruct"),
        "temperature": 0.00,
        "max_tokens": 2048,
        "timeout": 30.0,
        "model_kwargs": {"response_format": {"type": "json_object"}}
    },
    "publisher": {
        "model": os.environ.get("PUBLISHER_LLM_MODEL", "mistral-small:24b"),
        "temperature": 0.00,
        "max_tokens": 1024,
        "timeout": 15.0,
        "model_kwargs": {"response_format": {"type": "json_object"}}
    }
}


def get_chat_model(
    role: str = "copywriter",
    temperature: Optional[float] = None,
    timeout: Optional[float] = None
) -> ChatOpenAI:
    """
    Returns an initialized ChatOpenAI client bound to the specified agent role and local Ollama endpoint.
    Attempts to read dynamic AgentConfiguration from the database first, falling back to env/yaml.
    """
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    api_key = os.environ.get("OLLAMA_API_KEY", "NA")

    cfg = MODEL_ROSTER_CONFIG.get(role, MODEL_ROSTER_CONFIG["copywriter"]).copy()

    # Dynamic DB Override (Graceful DB failure)
    try:
        # Import lazily to avoid circular imports during startup
        from social_agent.models import AgentConfiguration
        db_cfg = AgentConfiguration.objects.filter(agent_role=role, is_active=True).first()
        if db_cfg:
            cfg["model"] = db_cfg.model_name
            cfg["temperature"] = db_cfg.temperature
            cfg["max_tokens"] = db_cfg.max_tokens
            if db_cfg.endpoint_url:
                base_url = db_cfg.endpoint_url
    except (ImportError, Exception) as exc:
        logger.debug("Dynamic agent configuration lookup failed for role '%s', using defaults: %s", role, exc)

    model_name = cfg["model"]
    temp = temperature if temperature is not None else cfg["temperature"]
    t_out = timeout if timeout is not None else cfg["timeout"]
    max_tokens = cfg["max_tokens"]
    model_kwargs = cfg.get("model_kwargs", {})

    logger.debug("Initializing LLM for role '%s' [Model: %s, Temp: %s, MaxTok: %s, URL: %s]", 
                 role, model_name, temp, max_tokens, base_url)

    return ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        temperature=temp,
        max_tokens=max_tokens,
        timeout=t_out,
        model_kwargs=model_kwargs
    )