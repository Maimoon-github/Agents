"""
social_agent/mcp_tools/client.py
Async FastMCP client manager using Streamable HTTP transport with:
- Per-tool routing to the correct MCP microservice endpoint
- JSON-RPC 2.0 protocol compliance
- Tenacity exponential-backoff + jitter retry policy
- Structured MCPToolExecutionError with retryability metadata
"""
import asyncio
import logging
import os
from typing import Dict, Any, Optional

import httpx

try:
    from tenacity import (
        retry,
        stop_after_attempt,
        wait_exponential,
        wait_random,
        retry_if_exception_type,
    )
    _HAS_TENACITY = True
except ImportError:
    _HAS_TENACITY = False

    class _DummyWait:  # type: ignore
        def __add__(self, other): return self
        def __radd__(self, other): return self

    def retry(*args, **kwargs):  # type: ignore
        def decorator(func):
            return func
        return decorator

    def stop_after_attempt(n): return n  # type: ignore
    def wait_exponential(**kwargs): return _DummyWait()  # type: ignore
    def wait_random(*args): return _DummyWait()  # type: ignore
    def retry_if_exception_type(*args): return lambda exc: isinstance(exc, args)  # type: ignore

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Tool → MCP Server routing table
# Maps tool name prefix to the environment variable holding the base URL.
# ──────────────────────────────────────────────────────────────────────────────
_TOOL_SERVER_MAP: Dict[str, str] = {
    # X / Twitter tools
    "post_x_tweet": "MCP_X_CONNECTOR_URL",
    "x_health_check": "MCP_X_CONNECTOR_URL",
    # Instagram tools
    "post_instagram": "MCP_INSTAGRAM_CONNECTOR_URL",
    "instagram_health_check": "MCP_INSTAGRAM_CONNECTOR_URL",
    # TikTok tools
    "post_tiktok": "MCP_TIKTOK_CONNECTOR_URL",
    "tiktok_health_check": "MCP_TIKTOK_CONNECTOR_URL",
    # Facebook tools
    "post_facebook": "MCP_FACEBOOK_CONNECTOR_URL",
    "facebook_health_check": "MCP_FACEBOOK_CONNECTOR_URL",
    # Web search / trend research tools
    "search_trends": "MCP_WEB_SEARCH_URL",
    "web_search": "MCP_WEB_SEARCH_URL",
    "health_check": "MCP_X_CONNECTOR_URL",  # default generic health check
}

_DEFAULT_SERVER_ENV = "MCP_X_CONNECTOR_URL"
_DEFAULT_SERVER_URL = "http://127.0.0.1:8001"


def _resolve_endpoint(tool_name: str) -> str:
    """
    Resolves the full MCP /mcp endpoint URL for a given tool name.

    Routing priority:
    1. Exact tool name match in _TOOL_SERVER_MAP
    2. Prefix match (e.g. 'post_x_*' → X connector)
    3. Fall back to MCP_X_CONNECTOR_URL/default

    Args:
        tool_name: Registered MCP tool identifier.

    Returns:
        Full endpoint URL string (e.g. 'http://127.0.0.1:8001/mcp').
    """
    env_key = _TOOL_SERVER_MAP.get(tool_name)

    if not env_key:
        # Prefix-based fallback routing
        if tool_name.startswith(("post_instagram", "instagram")):
            env_key = "MCP_INSTAGRAM_CONNECTOR_URL"
        elif tool_name.startswith(("post_tiktok", "tiktok")):
            env_key = "MCP_TIKTOK_CONNECTOR_URL"
        elif tool_name.startswith(("post_facebook", "facebook")):
            env_key = "MCP_FACEBOOK_CONNECTOR_URL"
        elif tool_name.startswith(("post_x", "x_twitter", "tweet")):
            env_key = "MCP_X_CONNECTOR_URL"
        elif tool_name.startswith(("search", "web", "trend")):
            env_key = "MCP_WEB_SEARCH_URL"
        else:
            env_key = _DEFAULT_SERVER_ENV

    base = os.environ.get(env_key, _DEFAULT_SERVER_URL).rstrip("/")

    # Try Django settings as secondary source
    if base == _DEFAULT_SERVER_URL:
        try:
            from django.conf import settings as dj_settings
            server_urls: Dict[str, str] = getattr(dj_settings, "MCP_SERVER_URLS", {})
            # Map env_key suffix to dict key
            key_alias = env_key.replace("MCP_", "").replace("_CONNECTOR_URL", "").replace("_URL", "").lower()
            if key_alias in server_urls:
                base = server_urls[key_alias].rstrip("/")
        except Exception:
            pass

    return f"{base}/mcp"


# ──────────────────────────────────────────────────────────────────────────────
# Domain exception
# ──────────────────────────────────────────────────────────────────────────────
class MCPToolExecutionError(Exception):
    """Domain-specific exception capturing failed MCP tool calls and upstream status codes."""

    def __init__(
        self,
        message: str,
        code: int = 500,
        retryable: bool = False,
        upstream_headers: Optional[Dict[str, str]] = None,
        backoff_seconds: float = 0.0,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable
        self.upstream_headers = upstream_headers or {}
        self.backoff_seconds = backoff_seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": "failed",
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "backoff_seconds": self.backoff_seconds,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Async MCP client
# ──────────────────────────────────────────────────────────────────────────────
class SocialMCPClient:
    """
    Asynchronous Client Manager interfacing LangGraph nodes with FastMCP tool servers.
    Communicates via JSON-RPC 2.0 protocol over Streamable HTTP (/mcp endpoint).

    Per-tool routing ensures each tool call lands on its designated MCP microservice,
    enforcing Tier 3 service isolation and token-sandboxed authentication.
    """

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        # Pooled clients keyed by base URL to allow connection reuse across calls
        self._clients: Dict[str, httpx.AsyncClient] = {}

    async def _get_client(self, base_url: str) -> httpx.AsyncClient:
        """Returns a pooled AsyncClient for the given base URL."""
        if base_url not in self._clients or self._clients[base_url].is_closed:
            self._clients[base_url] = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=5.0),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=30),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
        return self._clients[base_url]

    async def close(self):
        """Gracefully closes all pooled HTTP client sessions."""
        for client in self._clients.values():
            if not client.is_closed:
                await client.aclose()
        self._clients.clear()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10) + wait_random(0, 2),
        retry=retry_if_exception_type((
            httpx.TransportError,
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.ReadError,
        )),
        reraise=True,
    )
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Invokes an MCP tool by name via JSON-RPC 2.0 over Streamable HTTP.
        Automatically routes to the correct MCP microservice based on tool_name.

        Args:
            tool_name: Registered tool identifier (e.g. 'post_x_tweet', 'search_trends').
            arguments: Dict matching the tool's input schema.

        Returns:
            Dict containing execution results or structured error details.

        Raises:
            MCPToolExecutionError: For non-retryable client errors and fatal failures.
        """
        endpoint = _resolve_endpoint(tool_name)
        client = await self._get_client(endpoint.rsplit("/mcp", 1)[0])

        # JSON-RPC 2.0 envelope
        payload = {
            "jsonrpc": "2.0",
            "id": f"call_{tool_name}_{asyncio.get_event_loop().time():.6f}",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        logger.info("Dispatching MCP tool '%s' → %s", tool_name, endpoint)

        try:
            response = await client.post(endpoint, json=payload)

            # ── Rate limiting (429) ───────────────────────────────────────
            if response.status_code == 429:
                reset_header = (
                    response.headers.get("x-rate-limit-reset")
                    or response.headers.get("Retry-After", "15")
                )
                try:
                    backoff = float(reset_header)
                except (ValueError, TypeError):
                    backoff = 15.0
                raise MCPToolExecutionError(
                    message=f"Rate limit exceeded on '{tool_name}'",
                    code=429,
                    retryable=True,
                    upstream_headers=dict(response.headers),
                    backoff_seconds=backoff,
                )

            # ── Non-retryable client 4xx errors ───────────────────────────
            if 400 <= response.status_code < 500:
                error_body = response.text
                is_duplicate = "duplicate" in error_body.lower() or response.status_code == 403
                raise MCPToolExecutionError(
                    message=f"Client error on '{tool_name}' [{response.status_code}]: {error_body[:200]}",
                    code=response.status_code,
                    retryable=not is_duplicate,
                    upstream_headers=dict(response.headers),
                )

            response.raise_for_status()
            data = response.json()

            # ── JSON-RPC error response ───────────────────────────────────
            if "error" in data:
                err = data["error"]
                err_code = err.get("code", 500)
                err_msg = err.get("message", "Unknown MCP execution error")
                raise MCPToolExecutionError(
                    message=f"MCP JSON-RPC Error [{err_code}]: {err_msg}",
                    code=err_code,
                    retryable=err_code in (-32000, -32001, 502, 503, 504),
                )

            # ── Normalise result payload ──────────────────────────────────
            result = data.get("result", {})
            if isinstance(result, dict):
                return result
            if isinstance(result, list) and result:
                # MCP content array — extract first text item
                first = result[0]
                if isinstance(first, dict) and first.get("type") == "text":
                    import json as _json
                    try:
                        return _json.loads(first.get("text", "{}"))
                    except Exception:
                        return {"status": "success", "data": first.get("text")}
                return first if isinstance(first, dict) else {"status": "success", "data": first}
            return {"status": "success", "data": result}

        except MCPToolExecutionError:
            raise
        except (httpx.TransportError, httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning("Transient transport failure on '%s' (%s): retrying…", tool_name, endpoint)
            raise
        except Exception as exc:
            logger.error(
                "Fatal failure on MCP tool '%s' at %s: %s", tool_name, endpoint, exc, exc_info=True
            )
            raise MCPToolExecutionError(
                message=f"Fatal MCP tool error on '{tool_name}': {exc!s}",
                code=500,
                retryable=False,
            ) from exc