"""
social_agent/mcp_tools/client.py
Async FastMCP client manager using Streamable HTTP transport and tenacity retries.
"""
import asyncio
import logging
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
except ImportError:
    class _DummyWait:
        def __add__(self, other): return self
    def retry(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    def stop_after_attempt(n): return n
    def wait_exponential(**kwargs): return _DummyWait()
    def wait_random(*args): return _DummyWait()
    def retry_if_exception_type(*args): return None

logger = logging.getLogger(__name__)


class MCPToolExecutionError(Exception):
    """Domain-specific exception capturing failed MCP tool calls and upstream status codes."""
    def __init__(
        self,
        message: str,
        code: int = 500,
        retryable: bool = False,
        upstream_headers: Optional[Dict[str, str]] = None,
        backoff_seconds: float = 0.0
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
            "backoff_seconds": self.backoff_seconds
        }


class SocialMCPClient:
    """
    Asynchronous Client Manager interfacing LangGraph nodes with FastMCP 3.4+ tool servers.
    Communicates via JSON-RPC 2.0 protocol over Streamable HTTP (/mcp endpoint).
    """
    def __init__(
        self,
        endpoint_url: str = "http://localhost:8001/mcp",
        timeout: float = 15.0
    ):
        self.endpoint_url = endpoint_url
        self.timeout = timeout
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Initializes or returns an active pooled async HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=5.0),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                }
            )
        return self._http_client

    async def close(self):
        """Gracefully shuts down the underlying HTTP client session."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10) + wait_random(0, 2),
        retry=retry_if_exception_type((
            httpx.TransportError,
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.ReadError
        )),
        reraise=True
    )
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Invokes an MCP tool by name via standard JSON-RPC 2.0 payload over Streamable HTTP.
        
        Args:
            tool_name: The registered tool identifier (e.g. 'post_x_tweet').
            arguments: Dictionary matching the tool's input schema.
            
        Returns:
            Dict containing execution results or structured error details.
        """
        client = await self._get_client()
        payload = {
            "jsonrpc": "2.0",
            "id": f"call_{tool_name}_{asyncio.get_event_loop().time()}",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        try:
            logger.info("Dispatching MCP tool call: %s", tool_name)
            response = await client.post(self.endpoint_url, json=payload)
            
            # Handle rate limiting (429)
            if response.status_code == 429:
                reset_header = response.headers.get("x-rate-limit-reset") or response.headers.get("Retry-After", "5")
                try:
                    backoff = float(reset_header)
                except ValueError:
                    backoff = 5.0
                raise MCPToolExecutionError(
                    message=f"Rate limit exceeded on '{tool_name}'",
                    code=429,
                    retryable=True,
                    upstream_headers=dict(response.headers),
                    backoff_seconds=backoff
                )
                
            # Handle non-retryable 4xx client errors (e.g. 403 Duplicate content, 400 Bad Schema)
            if 400 <= response.status_code < 500:
                error_body = response.text
                is_duplicate = "duplicate" in error_body.lower() or response.status_code == 403
                raise MCPToolExecutionError(
                    message=f"Client error on '{tool_name}': {error_body}",
                    code=response.status_code,
                    retryable=not is_duplicate,
                    upstream_headers=dict(response.headers)
                )

            response.raise_for_status()
            data = response.json()
            
            # Check for JSON-RPC error response
            if "error" in data:
                err = data["error"]
                err_code = err.get("code", 500)
                err_msg = err.get("message", "Unknown MCP execution error")
                raise MCPToolExecutionError(
                    message=f"MCP Error [{err_code}]: {err_msg}",
                    code=err_code,
                    retryable=err_code in (-32000, -32001, 502, 503, 504)
                )
                
            result = data.get("result", {})
            if isinstance(result, dict):
                return result
            elif isinstance(result, list) and result:
                return result[0]
            return {"status": "success", "data": result}
            
        except MCPToolExecutionError:
            raise
        except (httpx.TransportError, httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning("Transient transport failure on '%s': %s (retrying...)", tool_name, str(exc))
            raise
        except Exception as exc:
            logger.error("Fatal failure on MCP tool call '%s': %s", tool_name, str(exc), exc_info=True)
            raise MCPToolExecutionError(
                message=f"Fatal MCP tool error: {str(exc)}",
                code=500,
                retryable=False
            ) from exc