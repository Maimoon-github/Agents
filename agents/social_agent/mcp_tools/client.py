"""
social_agent/mcp_tools/client.py
Standardized FastMCP client interfaces for social platform execution.
"""
import asyncio
from typing import Dict, Any, List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


class MCPToolExecutionError(Exception):
    """Raised when an MCP tool execution fails after retries."""
    pass


class SocialMCPClient:
    """
    Client interface connecting the agent layer to local or remote FastMCP servers.
    Handles JSON-RPC 2.0 tool invocation, schema validation, and exponential backoff.
    """
    def __init__(self, endpoint_url: str = "http://localhost:8001"):
        self.endpoint_url = endpoint_url

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(MCPToolExecutionError),
        reraise=True
    )
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a registered MCP tool via JSON-RPC protocol with retry/backoff.
        """
        try:
            # Simulated async MCP call over SSE/stdio transport
            await asyncio.sleep(0.05)
            
            if tool_name == "post_x_tweet":
                text = arguments.get("text", "")
                if len(text) > 280:
                    raise ValueError("X/Twitter character limit exceeded (280 max).")
                return {"status": "success", "post_id": f"x_{uuid_short()}", "platform": "x_twitter"}
            
            elif tool_name == "post_instagram":
                caption = arguments.get("caption", "")
                media_url = arguments.get("media_url")
                if not media_url:
                    raise ValueError("Instagram requires at least one image/video media_url.")
                return {"status": "success", "post_id": f"ig_{uuid_short()}", "platform": "instagram"}
            
            elif tool_name == "post_tiktok":
                video_url = arguments.get("video_url")
                if not video_url:
                    raise ValueError("TikTok posting requires a valid video_url.")
                return {"status": "success", "post_id": f"tt_{uuid_short()}", "platform": "tiktok"}
            
            elif tool_name == "search_trends":
                query = arguments.get("query", "")
                return {
                    "trends": [
                        f"Trend insights for '{query}' - 2026 Engagement Surge",
                        "Audience preference: High educational value, short-form visual hooks."
                    ]
                }
            
            else:
                raise NotImplementedError(f"MCP tool '{tool_name}' not registered.")
                
        except Exception as e:
            raise MCPToolExecutionError(f"MCP Error on '{tool_name}': {str(e)}") from e


def uuid_short() -> str:
    import uuid
    return str(uuid.uuid4())[:8]