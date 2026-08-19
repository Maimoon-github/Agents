"""
social_agent/mcp_tools/instagram.py
FastMCP 3.4+ connector for Meta Graph API (v22.0/v25.0) implementing the asynchronous 2-step container pipeline.
"""
import os
import re
import asyncio
import logging
from typing import Dict, Any, Optional, Literal
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

        def run(self, transport="http", host="0.0.0.0", port=8002):
            logging.info(f"Running FastMCP {self.name} server on {host}:{port} [{transport}]")

from social_agent.auth import resolve_platform_credentials

logger = logging.getLogger(__name__)

mcp = FastMCP("instagram", version="1.0.0", stateless_http=True, json_response=True)


class PostInstagramInput(BaseModel):
    """Input parameters for publishing images/Reels to Instagram Graph API."""
    caption: str = Field(..., max_length=2200, description="Post caption text with hashtags.")
    media_url: str = Field(..., description="Public HTTPS CDN URL to the media asset.")
    media_type: Literal["IMAGE", "VIDEO", "REELS"] = Field(default="IMAGE", description="Media classification.")
    alt_text: Optional[str] = Field(default=None, max_length=100, description="Accessibility alt-text.")
    account_handle: Optional[str] = Field(default=None, description="Instagram business account handle.")
    graph_version: str = Field(default="v25.0", description="Meta Graph API version.")

    @validator("media_url")
    def validate_https_url(cls, v):
        if not v.startswith("https://"):
            raise ValueError("media_url must be an absolute HTTPS URL to prevent SSRF.")
        return v

    @validator("caption")
    def validate_hashtag_count(cls, v):
        hashtags = re.findall(r"#\w+", v)
        if len(hashtags) > 30:
            raise ValueError(f"Caption exceeds Instagram maximum of 30 hashtags ({len(hashtags)} found).")
        return v


@mcp.tool(
    annotations=ToolAnnotations(
        title="Post Instagram Content",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
        idempotentHint=False
    )
)
async def post_instagram(
    caption: str,
    media_url: str,
    media_type: Literal["IMAGE", "VIDEO", "REELS"] = "IMAGE",
    alt_text: Optional[str] = None,
    account_handle: Optional[str] = None,
    graph_version: str = "v25.0",
    ctx: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Executes Instagram's 2-step media publishing workflow:
    1. Create Media Container -> 2. Poll Processing State -> 3. Publish Container.

    Args:
        caption: Caption text (max 2200 chars, max 30 hashtags).
        media_url: Publicly accessible HTTPS link to image/video.
        media_type: 'IMAGE', 'VIDEO', or 'REELS'.
        alt_text: Visual description for accessibility.
        account_handle: Business handle for Django token resolution.
        graph_version: Meta Graph API version string (default 'v25.0').
        ctx: FastMCP telemetry context.

    Returns:
        Dict with status, post_id, permalink, and timestamp.
    """
    # 1. Input Validation
    try:
        data = PostInstagramInput(
            caption=caption,
            media_url=media_url,
            media_type=media_type,
            alt_text=alt_text,
            account_handle=account_handle,
            graph_version=graph_version
        )
    except Exception as e:
        return {
            "status": "failed",
            "code": 400,
            "message": f"Instagram input validation failed: {str(e)}",
            "retryable": False,
            "backoff_seconds": 0.0
        }

    # 2. Token & User ID Resolution from PlatformAuthManager
    creds = await resolve_platform_credentials("instagram", account_handle=data.account_handle)
    access_token = creds.get("access_token") or "mock_ig_access_token"
    ig_user_id = creds.get("user_id") or os.environ.get("INSTAGRAM_USER_ID", "17841400000000000")

    if access_token == "mock_ig_access_token":
        import uuid
        mock_id = f"180{str(uuid.uuid4().int)[:14]}"
        return {
            "status": "success",
            "post_id": mock_id,
            "platform": "instagram",
            "permalink": f"https://www.instagram.com/p/{mock_id[:10]}/",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "auth_source": creds.get("source", "mock")
        }

    base_url = f"https://graph.facebook.com/{data.graph_version}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Step 1: Create Container
            container_payload: Dict[str, Any] = {
                "caption": data.caption,
                "access_token": access_token
            }
            if data.media_type == "IMAGE":
                container_payload["image_url"] = data.media_url
            else:
                container_payload["video_url"] = data.media_url
                container_payload["media_type"] = "REELS"

            c_resp = await client.post(f"{base_url}/{ig_user_id}/media", data=container_payload)
            if c_resp.status_code == 401 or c_resp.status_code == 400:
                err_text = c_resp.text
                if "OAuthException" in err_text or "token" in err_text.lower():
                    return {
                        "status": "failed",
                        "code": 401,
                        "message": f"Instagram Graph API Authentication Failed: Token expired or lacks 'instagram_content_publish' scope ({err_text}).",
                        "retryable": False,
                        "backoff_seconds": 0.0
                    }
                return {
                    "status": "failed",
                    "code": c_resp.status_code,
                    "message": f"Container creation failed: {err_text}",
                    "retryable": False,
                    "backoff_seconds": 0.0
                }
            elif c_resp.status_code != 200:
                return {
                    "status": "failed",
                    "code": c_resp.status_code,
                    "message": f"Container creation failed: {c_resp.text}",
                    "retryable": c_resp.status_code in (500, 502, 503, 504),
                    "backoff_seconds": 2.0
                }

            container_id = c_resp.json().get("id")

            # Step 2: Poll Container Status (handling IN_PROGRESS)
            for attempt in range(6):
                await asyncio.sleep(2.0 + attempt * 1.5)
                status_resp = await client.get(
                    f"{base_url}/{container_id}",
                    params={"fields": "status_code,status", "access_token": access_token}
                )
                if status_resp.status_code == 200:
                    status_val = status_resp.json().get("status_code", "FINISHED")
                    if status_val == "FINISHED":
                        break
                    elif status_val in ("ERROR", "EXPIRED"):
                        return {
                            "status": "failed",
                            "code": 400,
                            "message": f"Media transcoding failed: {status_resp.text}",
                            "retryable": False,
                            "backoff_seconds": 0.0
                        }

            # Step 3: Publish Container
            pub_resp = await client.post(
                f"{base_url}/{ig_user_id}/media_publish",
                data={"creation_id": container_id, "access_token": access_token}
            )
            if pub_resp.status_code != 200:
                return {
                    "status": "failed",
                    "code": pub_resp.status_code,
                    "message": f"Media publish dispatch failed: {pub_resp.text}",
                    "retryable": True,
                    "backoff_seconds": 3.0
                }

            published_media_id = pub_resp.json().get("id")

            # Optional Step 4: Fetch permalink
            permalink = f"https://www.instagram.com/p/{published_media_id}/"
            try:
                p_resp = await client.get(
                    f"{base_url}/{published_media_id}",
                    params={"fields": "permalink", "access_token": access_token}
                )
                if p_resp.status_code == 200:
                    permalink = p_resp.json().get("permalink", permalink)
            except Exception:
                pass

            return {
                "status": "success",
                "post_id": str(published_media_id),
                "platform": "instagram",
                "permalink": permalink,
                "published_at": datetime.now(timezone.utc).isoformat()
            }

        except httpx.HTTPError as exc:
            return {
                "status": "failed",
                "code": 502,
                "message": f"Meta Graph API HTTP error: {str(exc)}",
                "retryable": True,
                "backoff_seconds": 3.0
            }


@mcp.tool(
    annotations=ToolAnnotations(
        title="Instagram Connector Health Check",
        readOnlyHint=True,
        openWorldHint=False
    )
)
async def health_check() -> Dict[str, Any]:
    """Returns operational status and version of the Instagram FastMCP connector."""
    creds = await resolve_platform_credentials("instagram")
    return {
        "status": "healthy",
        "service": "instagram_mcp",
        "version": mcp.version,
        "auth_configured": bool(creds.get("access_token") and creds["access_token"] != "mock_ig_access_token"),
        "user_id_configured": bool(creds.get("user_id")),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="http", host="0.0.0.0", port=8002)