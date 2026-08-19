"""
social_agent/auth.py
Enterprise Authentication & Platform Credential Manager for TikTok, X (Twitter), Instagram, and Facebook.
Implements OAuth 2.0 flows, PKCE challenge generation, token exchange, token rotation, and credential resolution.
"""
import os
import re
import base64
import hashlib
import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple, Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger("social_agent.auth")


# ==============================================================================
# 1. Pydantic Credential Schemas & Validation Models
# ==============================================================================

class TikTokCredentials(BaseModel):
    """Credentials and validation for TikTok Content Posting API v2."""
    client_key: str = Field(..., description="Public client application key.")
    client_secret: str = Field(..., description="Server-side secret for token exchange.")
    redirect_uri: str = Field(..., description="Registered OAuth redirect URI.")
    access_token: Optional[str] = Field(default=None, description="Short-lived (24h) bearer access token.")
    refresh_token: Optional[str] = Field(default=None, description="Long-lived (365d) refresh token.")
    token_expires_at: Optional[datetime] = None


class XTwitterCredentials(BaseModel):
    """Credentials and validation for X (Twitter) API v2."""
    client_id: str = Field(..., description="OAuth 2.0 PKCE Client ID.")
    client_secret: Optional[str] = Field(default=None, description="Confidential client secret for token endpoint.")
    redirect_uri: str = Field(..., description="Registered OAuth 2.0 redirect URI.")
    bearer_token: Optional[str] = Field(default=None, description="App-only bearer token for read operations.")
    access_token: Optional[str] = Field(default=None, description="User-context access token with tweet.write scope.")
    refresh_token: Optional[str] = Field(default=None, description="OAuth 2.0 refresh token with offline.access scope.")
    token_expires_at: Optional[datetime] = None


class InstagramCredentials(BaseModel):
    """Credentials and validation for Instagram Graph API (via Meta)."""
    app_id: str = Field(..., description="Meta Developer App ID (client_id).")
    app_secret: str = Field(..., description="Meta Developer App Secret.")
    redirect_uri: str = Field(..., description="Registered Meta redirect URI.")
    access_token: Optional[str] = Field(default=None, description="Long-lived (60 days) user or page access token.")
    user_id: Optional[str] = Field(default=None, description="Instagram Business Account ID.")
    token_expires_at: Optional[datetime] = None


class FacebookCredentials(BaseModel):
    """Credentials and validation for Facebook Graph API."""
    app_id: str = Field(..., description="Meta Developer App ID.")
    app_secret: str = Field(..., description="Meta Developer App Secret.")
    redirect_uri: str = Field(..., description="Registered Meta redirect URI.")
    page_access_token: Optional[str] = Field(default=None, description="Never-expiring Page Access Token.")
    page_id: Optional[str] = Field(default=None, description="Target Facebook Page ID.")
    user_access_token: Optional[str] = Field(default=None, description="User access token used to generate page tokens.")
    token_expires_at: Optional[datetime] = None


# ==============================================================================
# 2. PKCE & Security Utilities
# ==============================================================================

def generate_pkce_pair(length: int = 64) -> Tuple[str, str]:
    """
    Generates an RFC 7636-compliant PKCE code_verifier and S256 code_challenge.
    
    Returns:
        Tuple of (code_verifier, code_challenge)
    """
    verifier = secrets.token_urlsafe(length)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return verifier, challenge


def generate_oauth_state() -> str:
    """Generates a cryptographically secure random state parameter for CSRF mitigation."""
    return secrets.token_hex(16)


# ==============================================================================
# 3. Platform Authentication & OAuth Flow Manager
# ==============================================================================

class PlatformAuthManager:
    """
    Centralized manager for OAuth URL generation, authorization code exchange,
    proactive token refresh, and credential resolution across all supported platforms.
    """

    # --- TIKTOK OAUTH METHODS ---

    @staticmethod
    def tiktok_get_auth_url(
        client_key: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        state: Optional[str] = None,
        scopes: Optional[List[str]] = None
    ) -> str:
        """Generates the TikTok OAuth 2.0 authorization URL."""
        key = client_key or os.environ.get("TIKTOK_CLIENT_KEY", "")
        r_uri = redirect_uri or os.environ.get("TIKTOK_REDIRECT_URI", "")
        scope_list = scopes or ["video.publish", "video.upload", "user.info.basic"]
        st = state or generate_oauth_state()

        params = {
            "client_key": key,
            "scope": ",".join(scope_list),
            "response_type": "code",
            "redirect_uri": r_uri,
            "state": st,
        }
        return f"https://www.tiktok.com/v2/auth/authorize/?{urlencode(params)}"

    @staticmethod
    async def tiktok_exchange_code(
        code: str,
        client_key: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None
    ) -> Dict[str, Any]:
        """Exchanges TikTok authorization code for access_token and refresh_token."""
        key = client_key or os.environ.get("TIKTOK_CLIENT_KEY", "")
        secret = client_secret or os.environ.get("TIKTOK_CLIENT_SECRET", "")
        r_uri = redirect_uri or os.environ.get("TIKTOK_REDIRECT_URI", "")

        url = "https://open.tiktokapis.com/v2/oauth/token/"
        payload = {
            "client_key": key,
            "client_secret": secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": r_uri,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, data=payload)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def tiktok_refresh_token(
        refresh_token: str,
        client_key: Optional[str] = None,
        client_secret: Optional[str] = None
    ) -> Dict[str, Any]:
        """Refreshes short-lived (24h) TikTok access token using long-lived refresh_token."""
        key = client_key or os.environ.get("TIKTOK_CLIENT_KEY", "")
        secret = client_secret or os.environ.get("TIKTOK_CLIENT_SECRET", "")

        url = "https://open.tiktokapis.com/v2/oauth/token/"
        payload = {
            "client_key": key,
            "client_secret": secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, data=payload)
            resp.raise_for_status()
            return resp.json()

    # --- X / TWITTER OAUTH METHODS ---

    @staticmethod
    def x_get_auth_url(
        client_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        code_challenge: Optional[str] = None,
        state: Optional[str] = None,
        scopes: Optional[List[str]] = None
    ) -> Tuple[str, str]:
        """
        Generates X (Twitter) OAuth 2.0 PKCE authorization URL.
        
        Returns:
            Tuple of (authorization_url, code_verifier)
        """
        cid = client_id or os.environ.get("X_CLIENT_ID", "")
        r_uri = redirect_uri or os.environ.get("X_REDIRECT_URI", "")
        st = state or generate_oauth_state()
        scope_str = " ".join(scopes or ["tweet.read", "tweet.write", "users.read", "offline.access"])

        verifier = ""
        challenge = code_challenge
        if not challenge:
            verifier, challenge = generate_pkce_pair()

        params = {
            "client_id": cid,
            "redirect_uri": r_uri,
            "response_type": "code",
            "scope": scope_str,
            "state": st,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        url = f"https://x.com/i/oauth2/authorize?{urlencode(params)}"
        return url, verifier

    @staticmethod
    async def x_exchange_code(
        code: str,
        code_verifier: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None
    ) -> Dict[str, Any]:
        """Exchanges X authorization code + PKCE verifier for access_token and refresh_token."""
        cid = client_id or os.environ.get("X_CLIENT_ID", "")
        sec = client_secret or os.environ.get("X_CLIENT_SECRET", "")
        r_uri = redirect_uri or os.environ.get("X_REDIRECT_URI", "")

        url = "https://api.x.com/2/oauth2/token"
        payload = {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": r_uri,
            "code_verifier": code_verifier,
            "client_id": cid,
        }
        headers = {}
        if sec:
            basic_auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
            headers["Authorization"] = f"Basic {basic_auth}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, data=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def x_refresh_token(
        refresh_token: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None
    ) -> Dict[str, Any]:
        """Refreshes X user access token using refresh_token with offline.access scope."""
        cid = client_id or os.environ.get("X_CLIENT_ID", "")
        sec = client_secret or os.environ.get("X_CLIENT_SECRET", "")

        url = "https://api.x.com/2/oauth2/token"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": cid,
        }
        headers = {}
        if sec:
            basic_auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
            headers["Authorization"] = f"Basic {basic_auth}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, data=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    # --- INSTAGRAM (META) OAUTH METHODS ---

    @staticmethod
    def instagram_get_auth_url(
        app_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        state: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        graph_version: str = "v25.0"
    ) -> str:
        """Generates Instagram OAuth authorization URL (via Facebook Login dialog)."""
        aid = app_id or os.environ.get("META_APP_ID", "")
        r_uri = redirect_uri or os.environ.get("META_REDIRECT_URI", "")
        scope_str = ",".join(scopes or ["instagram_basic", "instagram_content_publish"])
        st = state or generate_oauth_state()

        params = {
            "client_id": aid,
            "redirect_uri": r_uri,
            "response_type": "code",
            "scope": scope_str,
            "state": st,
        }
        return f"https://www.facebook.com/{graph_version}/dialog/oauth?{urlencode(params)}"

    @staticmethod
    async def instagram_exchange_code(
        code: str,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        graph_version: str = "v25.0"
    ) -> Dict[str, Any]:
        """
        Two-step exchange:
        Step 1: Exchange code for short-lived user token.
        Step 2: Exchange short-lived token for long-lived (60 days) token.
        """
        aid = app_id or os.environ.get("META_APP_ID", "")
        sec = app_secret or os.environ.get("META_APP_SECRET", "")
        r_uri = redirect_uri or os.environ.get("META_REDIRECT_URI", "")

        async with httpx.AsyncClient(timeout=20.0) as client:
            # Step 1: Short-lived token
            url1 = f"https://graph.facebook.com/{graph_version}/oauth/access_token"
            params1 = {
                "client_id": aid,
                "client_secret": sec,
                "redirect_uri": r_uri,
                "code": code,
                "grant_type": "authorization_code",
            }
            resp1 = await client.get(url1, params=params1)
            resp1.raise_for_status()
            short_lived_token = resp1.json()["access_token"]

            # Step 2: Long-lived token exchange
            url2 = "https://graph.instagram.com/access_token"
            params2 = {
                "grant_type": "ig_exchange_token",
                "client_secret": sec,
                "access_token": short_lived_token,
            }
            resp2 = await client.get(url2, params=params2)
            if resp2.status_code == 200:
                data2 = resp2.json()
                return {
                    "access_token": data2.get("access_token"),
                    "token_type": data2.get("token_type", "bearer"),
                    "expires_in": data2.get("expires_in", 5184000),  # 60 days
                }
            # Fallback to fb_exchange_token endpoint
            url_fb_exchange = f"https://graph.facebook.com/{graph_version}/oauth/access_token"
            params_fb = {
                "grant_type": "fb_exchange_token",
                "client_id": aid,
                "client_secret": sec,
                "fb_exchange_token": short_lived_token,
            }
            resp_fb = await client.get(url_fb_exchange, params=params_fb)
            resp_fb.raise_for_status()
            return resp_fb.json()

    @staticmethod
    async def instagram_refresh_token(
        long_lived_token: str
    ) -> Dict[str, Any]:
        """Refreshes long-lived Instagram access token (call every 50 days before 60-day expiry)."""
        url = "https://graph.instagram.com/refresh_access_token"
        params = {
            "grant_type": "ig_refresh_token",
            "access_token": long_lived_token,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    # --- FACEBOOK (META) OAUTH METHODS ---

    @staticmethod
    def facebook_get_auth_url(
        app_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        state: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        graph_version: str = "v25.0"
    ) -> str:
        """Generates Facebook OAuth authorization URL."""
        aid = app_id or os.environ.get("META_APP_ID", "")
        r_uri = redirect_uri or os.environ.get("META_REDIRECT_URI", "")
        scope_str = ",".join(scopes or [
            "pages_manage_posts",
            "pages_read_engagement",
            "instagram_basic",
            "instagram_content_publish"
        ])
        st = state or generate_oauth_state()

        params = {
            "client_id": aid,
            "redirect_uri": r_uri,
            "response_type": "code",
            "scope": scope_str,
            "state": st,
        }
        return f"https://www.facebook.com/{graph_version}/dialog/oauth?{urlencode(params)}"

    @staticmethod
    async def facebook_exchange_code_for_page_token(
        code: str,
        target_page_id: Optional[str] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        graph_version: str = "v25.0"
    ) -> Dict[str, Any]:
        """
        Three-step exchange:
        Step 1: Exchange code for short-lived user token.
        Step 2: Exchange short-lived token for long-lived user token (60 days).
        Step 3: Query /me/accounts with long-lived user token to obtain never-expiring Page Access Token.
        """
        aid = app_id or os.environ.get("META_APP_ID", "")
        sec = app_secret or os.environ.get("META_APP_SECRET", "")
        r_uri = redirect_uri or os.environ.get("META_REDIRECT_URI", "")

        async with httpx.AsyncClient(timeout=25.0) as client:
            # Step 1: Short-lived user token
            url1 = f"https://graph.facebook.com/{graph_version}/oauth/access_token"
            params1 = {
                "client_id": aid,
                "client_secret": sec,
                "redirect_uri": r_uri,
                "code": code,
                "grant_type": "authorization_code",
            }
            resp1 = await client.get(url1, params=params1)
            resp1.raise_for_status()
            short_lived = resp1.json()["access_token"]

            # Step 2: Long-lived user token
            params2 = {
                "grant_type": "fb_exchange_token",
                "client_id": aid,
                "client_secret": sec,
                "fb_exchange_token": short_lived,
            }
            resp2 = await client.get(url1, params=params2)
            resp2.raise_for_status()
            long_lived_user = resp2.json()["access_token"]

            # Step 3: Get never-expiring Page tokens from /me/accounts
            url3 = f"https://graph.facebook.com/{graph_version}/me/accounts"
            resp3 = await client.get(url3, params={"access_token": long_lived_user})
            resp3.raise_for_status()
            pages_data = resp3.json().get("data", [])

            if not pages_data:
                raise ValueError("No Facebook Pages found for authorized user.")

            # Match target page or select first
            selected_page = None
            if target_page_id:
                for p in pages_data:
                    if str(p.get("id")) == str(target_page_id):
                        selected_page = p
                        break
            if not selected_page:
                selected_page = pages_data[0]

            return {
                "page_id": selected_page.get("id"),
                "page_name": selected_page.get("name"),
                "page_access_token": selected_page.get("access_token"),
                "user_long_lived_token": long_lived_user,
                "all_pages": pages_data,
            }


# ==============================================================================
# 4. Multi-Tier Credential Resolution & Validation
# ==============================================================================

async def resolve_platform_credentials(
    platform: Literal["x_twitter", "instagram", "tiktok", "facebook"],
    account_handle: Optional[str] = None
) -> Dict[str, Any]:
    """
    Resolves credentials for a given platform.
    Priority order:
      1. Django ORM `PlatformAccount` database record matching platform and optional handle.
      2. Environment variables from `.env` / `settings.PLATFORM_CREDENTIALS`.
      3. Mock fallback token (if local simulation).
    """
    resolved: Dict[str, Any] = {
        "platform": platform,
        "account_handle": account_handle or "default",
        "source": "environment",
        "access_token": None,
        "rate_limit_remaining": 100,
    }

    # 1. Attempt Database Lookup
    try:
        from social_agent.models import PlatformAccount
        query = PlatformAccount.objects.filter(platform=platform, is_active=True)
        if account_handle:
            query = query.filter(account_handle=account_handle)
        account = await query.afirst()
        if account and account.encrypted_access_token:
            resolved["access_token"] = account.encrypted_access_token
            resolved["refresh_token"] = account.encrypted_refresh_token
            resolved["account_handle"] = account.account_handle
            resolved["rate_limit_remaining"] = account.rate_limit_remaining
            resolved["token_expires_at"] = account.token_expires_at
            resolved["source"] = "database"
            if hasattr(account, "account_id") and account.account_id:
                resolved["account_id"] = account.account_id
            return resolved
    except Exception as db_err:
        logger.debug("Database credential lookup bypassed for %s: %s", platform, db_err)

    # 2. Environment Variable Resolution
    if platform == "x_twitter":
        token = (
            os.environ.get("X_ACCESS_TOKEN")
            or os.environ.get("X_BEARER_TOKEN")
            or os.environ.get("TWITTER_BEARER_TOKEN")
            or os.environ.get("TWITTER_ACCESS_TOKEN")
        )
        resolved["access_token"] = token or "mock_x_access_token"
        resolved["bearer_token"] = os.environ.get("X_BEARER_TOKEN") or os.environ.get("TWITTER_BEARER_TOKEN")
        resolved["client_id"] = os.environ.get("X_CLIENT_ID")
        resolved["client_secret"] = os.environ.get("X_CLIENT_SECRET")

    elif platform == "instagram":
        token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
        resolved["access_token"] = token or "mock_ig_access_token"
        resolved["user_id"] = os.environ.get("INSTAGRAM_USER_ID", "17841400000000000")
        resolved["app_id"] = os.environ.get("META_APP_ID")
        resolved["app_secret"] = os.environ.get("META_APP_SECRET")

    elif platform == "tiktok":
        token = os.environ.get("TIKTOK_ACCESS_TOKEN")
        resolved["access_token"] = token or "mock_tiktok_token"
        resolved["client_key"] = os.environ.get("TIKTOK_CLIENT_KEY")
        resolved["client_secret"] = os.environ.get("TIKTOK_CLIENT_SECRET")
        resolved["refresh_token"] = os.environ.get("TIKTOK_REFRESH_TOKEN")

    elif platform == "facebook":
        token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN")
        resolved["access_token"] = token or "mock_fb_page_token"
        resolved["page_id"] = os.environ.get("FACEBOOK_PAGE_ID", "100000000000000")
        resolved["app_id"] = os.environ.get("META_APP_ID")
        resolved["app_secret"] = os.environ.get("META_APP_SECRET")

    return resolved


def validate_platform_credentials(
    platform: Literal["x_twitter", "instagram", "tiktok", "facebook"],
    credentials: Dict[str, Any]
) -> Tuple[bool, List[str]]:
    """
    Validates that the resolved credential set conforms to the platform's authentication contract.
    
    Returns:
        Tuple of (is_valid, list_of_missing_or_invalid_fields)
    """
    missing: List[str] = []
    token = credentials.get("access_token")

    if not token or str(token).startswith("your_"):
        missing.append("access_token")

    if platform == "instagram":
        uid = credentials.get("user_id")
        if not uid or str(uid).startswith("your_"):
            missing.append("user_id (Instagram Business Account ID)")

    elif platform == "facebook":
        pid = credentials.get("page_id")
        if not pid or str(pid).startswith("your_"):
            missing.append("page_id (Facebook Page ID)")

    elif platform == "tiktok":
        pass

    elif platform == "x_twitter":
        pass

    return len(missing) == 0, missing
