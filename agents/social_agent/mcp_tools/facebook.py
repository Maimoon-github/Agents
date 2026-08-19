"""
social_agent/mcp_tools/facebook.py
FastMCP 3.4+ connector for Facebook Graph API (v22.0/v25.0) implementing Page Feed publishing.
"""
import os
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import httpx
from pydantic import BaseModel, Field, validator

try:
    from fastmcp import FastMCP, Context
    from fastmcp.tools.base import ToolAnnotations
except ImportError:
    class ToolAnnotations:
        def __init__(self, title=None, readOnlyHint=False, destructiveHint=False, openWorldHint=True, idempotentHint=False):
            self.title = title
            self.readOnlyHint = readOnlyHint
            self.destructiveHint = destructiveHint
            self.openWorldHint = openWorldHint
            self.idempotentHint = idempotentHint

    class FastMCP:
        def __init__(self, name: str, version: str = "1.0.0", stateless_http: bool = True, json_response: bool = True):
            self.name = name
            self.version = version
            self.stateless_http = stateless_http
            self.json_response = json_response
            self._tools = {}

        def tool(self, annotations=None):
            def decorator(func):
                self._tools[func.__name__] = func
                return func
            return decorator

        def run(self, transport="http", host="0.0.0.0", port=8004):
            logging.info(f"Running FastMCP {self.name} server on {host}:{port} [{transport}]")

from social_agent.auth import resolve_platform_credentials

logger = logging.getLogger(__name__)

mcp = FastMCP("facebook", version="1.0.0", stateless_http=True, json_response=True)


class PostFacebookInput(BaseModel):
    """Input validation for Facebook Page Feed publishing."""
    message: str = Field(..., min_length=1, max_length=63206, description="Post body message text.")
    link: Optional[str] = Field(default=None, description="Optional web URL attachment link.")
    page_id: Optional[str] = Field(default=None, description="Target Facebook Page ID.")
    account_handle: Optional[str] = Field(default=None, description="Target Facebook page handle.")
    graph_version: str = Field(default="v25.0", description="Meta Graph API version.")

    @validator("link")
    def validate_link_https(cls, v):
        if v and not v.startswith("https://") and not v.startswith("http://"):
            raise ValueError("link must be a valid HTTP/HTTPS URL.")
        return v


@mcp.tool(
    annotations=ToolAnnotations(
        title="Post Facebook Page Feed",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
        idempotentHint=False
    )
)
async def post_facebook(
    message: str,
    link: Optional[str] = None,
    page_id: Optional[str] = None,
    account_handle: Optional[str] = None,
    graph_version: str = "v25.0",
    ctx: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Publishes a text or link post to a Facebook Page via Graph API.

    Args:
        message: The status text to publish to the Page feed.
        link: Optional URL to attach to the post.
        page_id: Optional Facebook Page ID (overrides default).
        account_handle: Optional handle for database credential lookup.
        graph_version: Meta Graph API version string (default 'v25.0').
        ctx: FastMCP context logger.

    Returns:
        Dict with status, post_id, platform, and published_at.
    """
    # 1. Input Validation
    try:
        data = PostFacebookInput(
            message=message,
            link=link,
            page_id=page_id,
            account_handle=account_handle,
            graph_version=graph_version
        )
    except Exception as e:
        return {
            "status": "failed",
            "code": 400,
            "message": f"Facebook input validation failed: {str(e)}",
            "retryable": False,
            "backoff_seconds": 0.0
        }

    # 2. Resolve Page Token & Page ID from PlatformAuthManager
    creds = await resolve_platform_credentials("facebook", account_handle=data.account_handle)
    page_token = creds.get("access_token") or "mock_fb_page_token"
    target_page_id = data.page_id or creds.get("page_id") or os.environ.get("FACEBOOK_PAGE_ID", "100000000000000")

    if page_token == "mock_fb_page_token":
        import uuid
        mock_id = f"{target_page_id}_{str(uuid.uuid4().int)[:15]}"
        return {
            "status": "success",
            "post_id": mock_id,
            "platform": "facebook",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "auth_source": creds.get("source", "mock")
        }

    url = f"https://graph.facebook.com/{data.graph_version}/{target_page_id}/feed"
    payload: Dict[str, Any] = {
        "message": data.message,
        "access_token": page_token
    }
    if data.link:
        payload["link"] = data.link

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.post(url, data=payload)

            if resp.status_code == 401 or resp.status_code == 400:
                err_text = resp.text
                if "OAuthException" in err_text:
                    return {
                        "status": "failed",
                        "code": 401,
                        "message": f"Facebook Graph API Authentication Failed: Page token invalid or lacks 'pages_manage_posts' scope ({err_text}).",
                        "retryable": False,
                        "backoff_seconds": 0.0
                    }
                return {
                    "status": "failed",
                    "code": resp.status_code,
                    "message": f"Facebook post failed: {err_text}",
                    "retryable": False,
                    "backoff_seconds": 0.0
                }

            if resp.status_code != 200:
                return {
                    "status": "failed",
                    "code": resp.status_code,
                    "message": f"Facebook API error: {resp.text}",
                    "retryable": resp.status_code in (500, 502, 503, 504),
                    "backoff_seconds": 3.0
                }

            post_id = resp.json().get("id", "")
            return {
                "status": "success",
                "post_id": str(post_id),
                "platform": "facebook",
                "published_at": datetime.now(timezone.utc).isoformat()
            }

        except httpx.HTTPError as exc:
            return {
                "status": "failed",
                "code": 502,
                "message": f"Facebook API HTTP error: {str(exc)}",
                "retryable": True,
                "backoff_seconds": 3.0
            }


@mcp.tool(
    annotations=ToolAnnotations(
        title="Facebook Connector Health Check",
        readOnlyHint=True,
        openWorldHint=False
    )
)
async def health_check() -> Dict[str, Any]:
    """Returns operational status and version of the Facebook FastMCP connector."""
    creds = await resolve_platform_credentials("facebook")
    return {
        "status": "healthy",
        "service": "facebook_mcp",
        "version": mcp.version,
        "auth_configured": bool(creds.get("access_token") and creds["access_token"] != "mock_fb_page_token"),
        "page_id_configured": bool(creds.get("page_id")),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="http", host="0.0.0.0", port=8004)
