"""
social_agent/mcp_tools/__init__.py
Unified package exports for FastMCP tool connectors and the async client manager.
Implements lazy attribute loading to prevent circular imports during Django startup.
"""
from typing import Any
from .client import SocialMCPClient, MCPToolExecutionError

__all__ = [
    "SocialMCPClient",
    "MCPToolExecutionError",
    "x_twitter_mcp",
    "instagram_mcp",
    "tiktok_mcp",
    "facebook_mcp",
    "web_search_mcp",
]


def __getattr__(name: str) -> Any:
    """Lazy-load FastMCP tool server instances to avoid premature module evaluation."""
    if name == "x_twitter_mcp":
        from .x_twitter import mcp as x_twitter_instance
        return x_twitter_instance
    elif name == "instagram_mcp":
        from .instagram import mcp as instagram_instance
        return instagram_instance
    elif name == "tiktok_mcp":
        from .tiktok import mcp as tiktok_instance
        return tiktok_instance
    elif name == "facebook_mcp":
        from .facebook import mcp as facebook_instance
        return facebook_instance
    elif name == "web_search_mcp":
        from .web_search import mcp as web_search_instance
        return web_search_instance
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")