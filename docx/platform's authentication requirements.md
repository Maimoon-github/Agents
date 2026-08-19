<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

## RESEARCH [ReAct Loop]

**Thought:** I need to gather official documentation for authentication credentials for TikTok, X (Twitter), Instagram, and Facebook APIs. I'll query official docs for each platform's credential types, generation steps, required scopes/permissions, and security/rotation policies.

**Action:** Search official docs for each platform's authentication requirements.

**Observations gathered:**

### TikTok (Content Posting API)

- **Credentials:** `client_key`, `client_secret`, `access_token`, `refresh_token`[^1][^2][^3][^4]
- **Auth flow:** OAuth 2.0 authorization code grant[^2][^3][^4]
- **Required scopes for posting:** `video.publish` (direct post), `video.upload` (drafts), `user.info.basic`[^5][^6][^7][^8]
- **Token lifecycle:** Short-lived access token (24 hours), refresh token (365 days)[^2]
- **Endpoints:** Auth URL: `https://www.tiktok.com/v2/auth/authorize/`, Token exchange: `https://open.tiktokapis.com/v2/oauth/token/`[^3][^4][^1][^2]
- **Security:** Store credentials in environment variables or secrets manager; never expose `client_secret` in client-side code[^2]


### X (Twitter) API v2

- **Credentials:** `BEARER_TOKEN` (app-only read), `API_KEY`/`API_SECRET` (OAuth 1.0a), `CLIENT_ID`/`CLIENT_SECRET` (OAuth 2.0 PKCE), `ACCESS_TOKEN` (user-context writes)[^9][^10][^11][^12][^13][^14][^15]
- **Auth flows:** Bearer Token (app-only read), OAuth 2.0 PKCE (user-delegated writes), OAuth 1.0a (legacy)[^11][^12][^13][^14][^16][^17][^18]
- **Required scopes for posting:** `tweet.read`, `tweet.write`, `users.read`, `offline.access`[^13][^19][^20][^21][^22]
- **Header:** `Authorization: Bearer <token>`[^12][^14][^23][^11][^13]
- **Token endpoint:** `https://api.x.com/2/oauth2/token`[^14]
- **Security:** API keys/tokens displayed once only; store in password manager or secure vault[^9]


### Instagram (Graph API)

- **Credentials:** `APP_ID` (client_id), `APP_SECRET` (client_secret), `access_token` (short-lived → long-lived)[^24][^25][^26][^27]
- **Auth flow:** OAuth 2.0 via Facebook Login[^26][^27][^24]
- **Required scopes for posting:** `instagram_basic`, `instagram_content_publish` (or `instagram_business_content_publish` for Instagram Login)[^25][^27][^28][^24][^26]
- **Token lifecycle:** Short-lived (1 hour) → long-lived (60 days); manual refresh required before expiry[^27][^24][^25][^26]
- **Endpoints:** Auth: `https://graph.facebook.com/v25.0/oauth/access_token`, Long-lived exchange: `https://graph.instagram.com/access_token`, Refresh: `https://graph.instagram.com/refresh_access_token`[^29][^26][^27]
- **Base URL:** `https://graph.instagram.com/v25.0` or `https://graph.facebook.com/v25.0`[^28][^25][^27]


### Facebook (Graph API)

- **Credentials:** `APP_ID`, `APP_SECRET`, `access_token` (User/Page/System User/App access tokens)[^30][^31][^32][^33][^34]
- **Auth flow:** OAuth 2.0; User access token → Page access token[^32][^33]
- **Required scopes for posting:** `pages_manage_posts`, `pages_read_engagement`, `instagram_basic`, `instagram_content_publish`[^33][^35][^36][^37][^30]
- **Token lifecycle:** Short-lived (1-2 hours) → long-lived (60 days) → Page tokens (never expire when obtained via long-lived user token)[^32][^33]
- **App access token generation:** `curl -X GET "https://graph.facebook.com/oauth/access_token?client_id={app-id}&client_secret={app-secret}&grant_type=client_credentials"`[^32]
- **Security:** App access tokens must never be in client-side code; use server-to-server only[^32]

***

## ANALYSIS [Chain-of-Thought]

### a) Mandatory vs Optional Credentials

| Platform | Mandatory | Optional/Context-Dependent |
| :-- | :-- | :-- |
| **TikTok** | `client_key`, `client_secret`, `access_token`, `refresh_token` | None for basic posting |
| **X** | `BEARER_TOKEN` (read-only) OR `CLIENT_ID` + `ACCESS_TOKEN` (writes) | `API_KEY`/`API_SECRET` (OAuth 1.0a legacy), `CLIENT_SECRET` (PKCE confidential clients) |
| **Instagram** | `APP_ID`, `APP_SECRET`, `access_token` (long-lived) | `refresh_token` workflow (manual refresh before 60 days) |
| **Facebook** | `APP_ID`, `APP_SECRET`, `access_token` (User or Page) | System User tokens (for automated business actions) |

### b) Critical Implementation Requirements

1. **Auth Flow:**
    - TikTok: OAuth 2.0 authorization code → token exchange → refresh token rotation[^4][^3][^2]
    - X: OAuth 2.0 PKCE for user-context writes; Bearer Token for app-only reads[^18][^19][^14]
    - Instagram: OAuth 2.0 → short-lived → long-lived exchange → manual refresh[^26][^27]
    - Facebook: OAuth 2.0 → User token → Page token (never-expiring)[^33][^32]
2. **Headers:**
    - All platforms: `Authorization: Bearer <access_token>`[^23][^11][^12][^13][^14]
    - X token exchange: Basic Auth with `client_id:client_secret`[^19]
3. **Environment Storage:**
    - All secrets (`client_secret`, `app_secret`, `api_secret`) must be server-side only[^2][^32]
    - Use environment variables or secrets manager[^2]
4. **SDK Requirements:**
    - No mandatory SDKs; all support raw HTTP with OAuth 2.0[^18][^27][^28]

### c) Failure Points \& Edge Cases

1. **Token Expiry:**
    - TikTok: 24-hour access token requires refresh every 18-20 hours[^2]
    - Instagram: 60-day long-lived token requires manual refresh before day 60[^27][^26]
    - Facebook: Page tokens never expire only if obtained via long-lived user token[^33]
    - X: PKCE tokens ~2 hours; `offline.access` scope enables refresh tokens[^21][^22][^19]
2. **Scope Mismatch:**
    - Posting requires explicit `*.write` or `*.publish` scopes; read-only tokens will fail[^7][^8][^38][^39][^5][^13]
3. **Callback URL Mismatch:**
    - X and TikTok require exact callback URL match in OAuth flow[^22][^40][^21][^18]
4. **App Review:**
    - TikTok Content Posting API requires app audit/compliance before production[^41][^7]
    - Facebook/Instagram require App Review for `instagram_content_publish`, `pages_manage_posts`[^35][^37]

***

## OUTPUT [Strict Format]

### A. Credential Specs

| Platform | Credential | Type | Purpose |
| :-- | :-- | :-- | :-- |
| **TikTok** | `client_key` | String (public) | App identifier for OAuth flow [^1][^2] |
|  | `client_secret` | String (secret) | Server-side secret for token exchange [^1][^2] |
|  | `access_token` | String (bearer) | Short-lived (24h) auth for API calls [^2][^4] |
|  | `refresh_token` | String (bearer) | Long-lived (365d) token for refreshing access [^2] |
| **X** | `BEARER_TOKEN` | String (bearer) | App-only read access [^10][^11][^15] |
|  | `CLIENT_ID` | String (public) | OAuth 2.0 PKCE app identifier [^18][^40] |
|  | `CLIENT_SECRET` | String (secret) | OAuth 2.0 PKCE confidential client secret [^19] |
|  | `ACCESS_TOKEN` | String (bearer) | User-context token with `tweet.write` scope [^13][^14] |
| **Instagram** | `APP_ID` | String (public) | Meta app identifier (client_id) [^24][^26] |
|  | `APP_SECRET` | String (secret) | Meta app secret for token exchange [^24][^26] |
|  | `access_token` | String (bearer) | Long-lived (60d) user/page token [^26][^27] |
| **Facebook** | `APP_ID` | String (public) | Meta app identifier [^32] |
|  | `APP_SECRET` | String (secret) | Meta app secret [^32] |
|  | `access_token` | String (bearer) | User/Page token (never-expiring Page tokens available) [^32][^33] |

### B. Implementation Checklist

1. **Developer Account \& App Setup**
    - [ ] Create developer account on each platform (TikTok, X, Meta)[^42][^9][^2]
    - [ ] Create app and note `client_key`/`client_secret` (TikTok), `CLIENT_ID`/`CLIENT_SECRET` (X), `APP_ID`/`APP_SECRET` (Meta)[^1][^24][^9][^32]
    - [ ] Configure callback/redirect URI (exact match required)[^40][^21][^22][^18]
2. **Scope/Permission Configuration**
    - [ ] TikTok: Request `video.publish`, `video.upload`, `user.info.basic`[^6][^8][^5][^7]
    - [ ] X: Enable `tweet.read`, `tweet.write`, `users.read`, `offline.access`[^20][^13][^19][^21]
    - [ ] Instagram: Request `instagram_basic`, `instagram_content_publish`[^24][^28][^26][^27]
    - [ ] Facebook: Request `pages_manage_posts`, `pages_read_engagement`, `instagram_basic`, `instagram_content_publish`[^37][^35][^33]
3. **OAuth Flow Implementation**
    - [ ] Implement authorization redirect with `client_id`, `scope`, `redirect_uri`, `state`[^3][^14][^26][^2]
    - [ ] Handle callback and extract `code` parameter[^14][^3][^26][^2]
    - [ ] Exchange `code` for `access_token` (+ `refresh_token` for TikTok/X)[^1][^14][^26][^2]
    - [ ] Instagram: Exchange short-lived token for long-lived (60d)[^26][^27]
    - [ ] Facebook: Exchange user token for Page token (never-expiring)[^33][^32]
4. **Secure Storage**
    - [ ] Store all secrets in environment variables or secrets manager[^2]
    - [ ] Never expose `client_secret`/`app_secret` in client-side code[^32][^2]
    - [ ] Use HTTPS for all token exchanges[^32]
5. **Token Rotation**
    - [ ] TikTok: Refresh access token every 18-20 hours using `refresh_token`[^2]
    - [ ] Instagram: Refresh long-lived token every 50 days[^27][^26]
    - [ ] X: Use `refresh_token` with `offline.access` scope when token expires (~2 hours)[^19][^21][^22]
    - [ ] Facebook: Page tokens never expire if obtained via long-lived user token[^33]
6. **API Request Formatting**
    - [ ] All requests: `Authorization: Bearer <access_token>` header[^11][^12][^13][^23][^14]
    - [ ] X token exchange: Basic Auth with `client_id:client_secret`[^19]

### C. Code Sample

```python
"""
Secure, minimal, functional implementation for TikTok, X, Instagram, Facebook.
Uses environment variables for all secrets. No hardcoded credentials.
"""

import os
import requests
from datetime import datetime, timedelta

# =============================================================================
# ENVIRONMENT CONFIGURATION (set these in your .env or secrets manager)
# =============================================================================

TIKTOK_CLIENT_KEY = os.environ["TIKTOK_CLIENT_KEY"]
TIKTOK_CLIENT_SECRET = os.environ["TIKTOK_CLIENT_SECRET"]
TIKTOK_REDIRECT_URI = os.environ["TIKTOK_REDIRECT_URI"]

X_CLIENT_ID = os.environ["X_CLIENT_ID"]
X_CLIENT_SECRET = os.environ["X_CLIENT_SECRET"]
X_REDIRECT_URI = os.environ["X_REDIRECT_URI"]
X_BEARER_TOKEN = os.environ["X_BEARER_TOKEN"]  # For app-only reads

META_APP_ID = os.environ["META_APP_ID"]
META_APP_SECRET = os.environ["META_APP_SECRET"]
META_REDIRECT_URI = os.environ["META_REDIRECT_URI"]

# =============================================================================
# TIKTOK: OAuth 2.0 + Token Refresh
# =============================================================================

def tiktok_get_auth_url(state: str) -> str:
    """Generate TikTok OAuth authorization URL."""
    scopes = "video.publish,video.upload,user.info.basic"
    return (
        f"https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={TIKTOK_CLIENT_KEY}"
        f"&scope={scopes}"
        f"&response_type=code"
        f"&redirect_uri={TIKTOK_REDIRECT_URI}"
        f"&state={state}"
    )

def tiktok_exchange_code(code: str) -> dict:
    """Exchange authorization code for access_token and refresh_token."""
    url = "https://open.tiktokapis.com/v2/oauth/token/"
    payload = {
        "client_key": TIKTOK_CLIENT_KEY,
        "client_secret": TIKTOK_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": TIKTOK_REDIRECT_URI,
    }
    resp = requests.post(url, data=payload)
    resp.raise_for_status()
    return resp.json()  # Contains access_token, refresh_token, expires_in

def tiktok_refresh_access_token(refresh_token: str) -> dict:
    """Refresh access token using refresh_token (call every 18-20 hours)."""
    url = "https://open.tiktokapis.com/v2/oauth/token/"
    payload = {
        "client_key": TIKTOK_CLIENT_KEY,
        "client_secret": TIKTOK_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    resp = requests.post(url, data=payload)
    resp.raise_for_status()
    return resp.json()

def tiktok_api_request(access_token: str, endpoint: str, method: str = "GET", json_data: dict = None):
    """Make authenticated TikTok API request."""
    url = f"https://open.tiktokapis.com/v2/{endpoint}"
    headers = {"Authorization": f"Bearer {access_token}"}
    if method == "GET":
        resp = requests.get(url, headers=headers)
    elif method == "POST":
        resp = requests.post(url, headers=headers, json=json_data)
    resp.raise_for_status()
    return resp.json()

# =============================================================================
# X (TWITTER): OAuth 2.0 PKCE + Bearer Token
# =============================================================================

def x_get_auth_url(state: str, code_challenge: str) -> str:
    """Generate X OAuth 2.0 PKCE authorization URL."""
    scopes = "tweet.read tweet.write users.read offline.access"
    return (
        f"https://x.com/i/oauth2/authorize"
        f"?client_id={X_CLIENT_ID}"
        f"&redirect_uri={X_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scopes}"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )

def x_exchange_code(code: str, code_verifier: str) -> dict:
    """Exchange authorization code for access_token and refresh_token."""
    url = "https://api.x.com/2/oauth2/token"
    payload = {
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": X_REDIRECT_URI,
        "code_verifier": code_verifier,
    }
    # X requires Basic Auth with client_id:client_secret
    from requests.auth import HTTPBasicAuth
    auth = HTTPBasicAuth(X_CLIENT_ID, X_CLIENT_SECRET)
    resp = requests.post(url, data=payload, auth=auth)
    resp.raise_for_status()
    return resp.json()

def x_api_request(access_token: str, endpoint: str, method: str = "GET", json_data: dict = None):
    """Make authenticated X API request."""
    url = f"https://api.x.com/2/{endpoint}"
    headers = {"Authorization": f"Bearer {access_token}"}
    if method == "GET":
        resp = requests.get(url, headers=headers)
    elif method == "POST":
        headers["Content-Type"] = "application/json"
        resp = requests.post(url, headers=headers, json=json_data)
    resp.raise_for_status()
    return resp.json()

def x_app_only_request(endpoint: str):
    """Make app-only read request using BEARER_TOKEN."""
    url = f"https://api.x.com/2/{endpoint}"
    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

# =============================================================================
# INSTAGRAM: OAuth 2.0 + Long-Lived Token Exchange
# =============================================================================

def instagram_get_auth_url(state: str) -> str:
    """Generate Instagram OAuth authorization URL (via Facebook Login)."""
    scopes = "instagram_basic,instagram_content_publish"
    return (
        f"https://www.facebook.com/v25.0/dialog/oauth"
        f"?client_id={META_APP_ID}"
        f"&redirect_uri={META_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scopes}"
        f"&state={state}"
    )

def instagram_exchange_code(code: str) -> str:
    """Exchange code for short-lived token, then for long-lived token (60 days)."""
    # Step 1: Get short-lived token
    url = "https://graph.facebook.com/v25.0/oauth/access_token"
    params = {
        "client_id": META_APP_ID,
        "client_secret": META_APP_SECRET,
        "redirect_uri": META_REDIRECT_URI,
        "code": code,
        "grant_type": "authorization_code",
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    short_lived = resp.json()["access_token"]

    # Step 2: Exchange for long-lived token (60 days)
    url = "https://graph.instagram.com/access_token"
    params = {
        "grant_type": "ig_exchange_token",
        "client_secret": META_APP_SECRET,
        "access_token": short_lived,
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()["access_token"]

def instagram_refresh_access_token(long_lived_token: str) -> str:
    """Refresh long-lived token (call every 50 days)."""
    url = "https://graph.instagram.com/refresh_access_token"
    params = {
        "grant_type": "ig_refresh_token",
        "access_token": long_lived_token,
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()["access_token"]

def instagram_api_request(access_token: str, endpoint: str, method: str = "GET", params: dict = None, json_data: dict = None):
    """Make authenticated Instagram Graph API request."""
    url = f"https://graph.instagram.com/v25.0/{endpoint}"
    if params is None:
        params = {}
    params["access_token"] = access_token
    if method == "GET":
        resp = requests.get(url, params=params)
    elif method == "POST":
        resp = requests.post(url, params=params, json=json_data)
    resp.raise_for_status()
    return resp.json()

# =============================================================================
# FACEBOOK: OAuth 2.0 + Page Access Token (Never-Expiring)
# =============================================================================

def facebook_get_auth_url(state: str) -> str:
    """Generate Facebook OAuth authorization URL."""
    scopes = "pages_manage_posts,pages_read_engagement,instagram_basic,instagram_content_publish"
    return (
        f"https://www.facebook.com/v25.0/dialog/oauth"
        f"?client_id={META_APP_ID}"
        f"&redirect_uri={META_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scopes}"
        f"&state={state}"
    )

def facebook_exchange_code(code: str) -> str:
    """Exchange code for long-lived user token, then get never-expiring Page token."""
    # Step 1: Get short-lived user token
    url = "https://graph.facebook.com/v25.0/oauth/access_token"
    params = {
        "client_id": META_APP_ID,
        "client_secret": META_APP_SECRET,
        "redirect_uri": META_REDIRECT_URI,
        "code": code,
        "grant_type": "authorization_code",
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    short_lived = resp.json()["access_token"]

    # Step 2: Exchange for long-lived user token (60 days)
    url = "https://graph.facebook.com/v25.0/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": META_APP_ID,
        "client_secret": META_APP_SECRET,
        "fb_exchange_token": short_lived,
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    long_lived_user = resp.json()["access_token"]

    # Step 3: Get Page token (never expires when obtained via long-lived user token)
    url = f"https://graph.facebook.com/v25.0/me/accounts"
    params = {"access_token": long_lived_user}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    pages = resp.json()["data"]
    # Return first Page token (or select by page_id in production)
    return pages[^0]["access_token"]

def facebook_api_request(access_token: str, endpoint: str, method: str = "GET", params: dict = None, json_data: dict = None):
    """Make authenticated Facebook Graph API request."""
    url = f"https://graph.facebook.com/v25.0/{endpoint}"
    if params is None:
        params = {}
    params["access_token"] = access_token
    if method == "GET":
        resp = requests.get(url, params=params)
    elif method == "POST":
        resp = requests.post(url, params=params, json=json_data)
    resp.raise_for_status()
    return resp.json()

# =============================================================================
# USAGE EXAMPLE (Post to all platforms)
# =============================================================================

if __name__ == "__main__":
    # Example: Post to X (requires user-context access_token from OAuth flow)
    x_access_token = os.environ["X_ACCESS_TOKEN"]
    tweet_payload = {"text": "Hello from X API v2!"}
    result = x_api_request(x_access_token, "tweets", method="POST", json_data=tweet_payload)
    print(f"X post result: {result}")

    # Example: Post to Instagram (requires long-lived access_token)
    ig_access_token = os.environ["INSTAGRAM_ACCESS_TOKEN"]
    ig_user_id = os.environ["INSTAGRAM_USER_ID"]
    # Step 1: Create media container
    container_payload = {
        "image_url": "https://example.com/image.jpg",
        "caption": "Hello from Instagram Graph API!",
    }
    container = instagram_api_request(ig_access_token, f"{ig_user_id}/media", method="POST", json_data=container_payload)
    container_id = container["id"]
    # Step 2: Publish container
    publish_payload = {"creation_id": container_id}
    publish = instagram_api_request(ig_access_token, f"{ig_user_id}/media_publish", method="POST", json_data=publish_payload)
    print(f"Instagram post result: {publish}")

    # Example: Post to Facebook Page
    fb_page_token = os.environ["FACEBOOK_PAGE_ACCESS_TOKEN"]
    page_id = os.environ["FACEBOOK_PAGE_ID"]
    fb_payload = {"message": "Hello from Facebook Graph API!"}
    fb_result = facebook_api_request(fb_page_token, f"{page_id}/feed", method="POST", json_data=fb_payload)
    print(f"Facebook post result: {fb_result}")

    # TikTok posting requires video upload flow (init → upload → publish)
    # See: https://open.tiktokapis.com/v2/post/publish/video/init/
```

**Environment variables required:**

```bash
# TikTok
TIKTOK_CLIENT_KEY=your_client_key
TIKTOK_CLIENT_SECRET=your_client_secret
TIKTOK_REDIRECT_URI=https://yourdomain.com/callback/tiktok

# X
X_CLIENT_ID=your_client_id
X_CLIENT_SECRET=your_client_secret
X_REDIRECT_URI=https://yourdomain.com/callback/x
X_BEARER_TOKEN=your_bearer_token  # For app-only reads
X_ACCESS_TOKEN=your_user_access_token  # For posting

# Meta (Instagram + Facebook)
META_APP_ID=your_app_id
META_APP_SECRET=your_app_secret
META_REDIRECT_URI=https://yourdomain.com/callback/meta
INSTAGRAM_ACCESS_TOKEN=your_long_lived_ig_token
INSTAGRAM_USER_ID=your_ig_business_account_id
FACEBOOK_PAGE_ACCESS_TOKEN=your_never_expiring_page_token
FACEBOOK_PAGE_ID=your_page_id
```

<span style="display:none">[^43][^44][^45][^46][^47][^48][^49][^50][^51][^52][^53][^54][^55][^56][^57][^58]</span>

<div align="center">⁂</div>

[^1]: https://developers.tiktok.com/doc/silent-login

[^2]: https://www.rapidevelopers.com/api-automations/how-to-automate-tiktok-comment-moderation-using-the-api

[^3]: https://posteverywhere.ai/blog/post-to-tiktok-api

[^4]: https://zernio.com/blog/tiktok-posting-api

[^5]: https://www.tokportal.com/learn/tiktok-content-posting-api-developer-guide

[^6]: https://multi-upload-tool.com/api/post-to-tiktok

[^7]: https://vorplabs.com/agent-tools/tiktok-content-posting-api

[^8]: https://postproxy.dev/blog/how-to-post-to-tiktok-via-api/

[^9]: https://docs.x.com/fundamentals/developer-portal

[^10]: https://github.com/xdevplatform/samples

[^11]: https://www.twitterapis.com/blogs/twitter-api-authentication

[^12]: https://www.getxapi.com/blogs/twitter-api-tutorial-2026-complete-guide

[^13]: https://bundle.social/blog/x-api-post-tweet

[^14]: https://postproxy.dev/blog/x-twitter-api-posting-integration-guide/

[^15]: https://www.twitterapis.com/blogs/how-to-get-twitter-api-key

[^16]: https://x-preview.mintlify.app/x-api/posts/retweets/integrate

[^17]: https://www.socialcrawl.dev/blog/x-twitter-api-2026

[^18]: https://docs.x.com/xdks/python/authentication

[^19]: https://dev.to/alex97po/x-twitter-media-upload-the-chunked-init-append-finalize-flow-33bb

[^20]: https://posteverywhere.ai/blog/schedule-x-twitter-posts-api

[^21]: https://zernio.com/blog/schedule-twitter-posts-via-api

[^22]: https://singhamandeep.com/x-api-oauth-2-0-authentication-setup/

[^23]: https://docs.x.com/x-api/webhooks/get-stream-links

[^24]: https://elfsight.com/blog/instagram-graph-api-complete-developer-guide-for-2026/

[^25]: https://gist.github.com/jameschapman2c/65eff9f54a2d350b17a6ce5127b9fe42

[^26]: https://zernio.com/blog/instagram-graph-api

[^27]: https://www.rapidevelopers.com/api-automations/how-to-automate-instagram-post-scheduling-using-the-api

[^28]: https://deepwiki.com/fbsamples/messenger-platform-samples/2.2-content-publishing

[^29]: https://dev.to/galtzo/ann-oauth2-v2017-h1a

[^30]: https://developers.facebook.com/documentation/pages-api/getting-started

[^31]: https://docs.n8n.io/integrations/builtin/credentials/facebookgraph

[^32]: https://developers.facebook.com/docs/facebook-login/access-tokens

[^33]: https://postproxy.dev/blog/facebook-graph-api-posting-guide/

[^34]: https://bundle.social/blog/facebook-graph-api

[^35]: https://www.socialcrawl.dev/blog/facebook-data-api-2026

[^36]: https://data365.co/blog/facebook-graph-api-alternative

[^37]: https://note.com/genjyo_papa/n/nfa25c9f710ad?hl=en

[^38]: https://docs.x.com/enterprise-api/posts/bookmarks/quickstart/manage-bookmarks

[^39]: https://x-preview.mintlify.app/x-api/direct-messages/manage/integrate

[^40]: https://github.com/jalehman/xc

[^41]: https://post-pulse.com/platforms/tiktok

[^42]: https://developers.tiktok.com/doc/

[^43]: https://developer.x.com/

[^44]: https://business-api.tiktok.com/portal/docs/identity/v1.3

[^45]: https://docs.n8n.io/integrations/builtin/credentials/twitter

[^46]: https://docs.twitterapis.com/docs/reference/account-session/user-user-login

[^47]: https://apis.io/apis/facebook/facebook-graph-api/

[^48]: https://gist.github.com/msramalho/4fc4bbc2f7ca58e0f6dc4d6de6215dc0?permalink_comment_id=5889029

[^49]: https://dev.to/lucas_ferreira/como-usar-a-api-graph-do-instagram-em-2026-4chb

[^50]: https://dev.to/yusuf_khalidd/kyfy-stkhdm-instagram-graph-api-fy-m-2026-c8e

[^51]: https://dev.to/antoine_laurentt/comment-utiliser-lapi-graph-instagram-en-2026--1dac

[^52]: https://dev.to/apilover/how-to-use-instagram-graph-api-in-2026-2762

[^53]: https://community.n8n.io/t/facebook-graph-api-token/260496

[^54]: https://www.greenwoodspellet.com/?_=/docs/graph-api/reference/application%23ugy7DKvAZSLDaOo7sutJgaAL4Rq5mS9vyGL3cL3rVA==

[^55]: https://developers.facebook.com/docs/instagram-api/getting-started

[^56]: https://generaltranslation.mintlify.app/fundamentals/authentication/guides/v2-authentication-mapping

[^57]: https://shadcnstudio.com/blog/full-stack-component-in-shadcn/

[^58]: https://wpsocialninja.com/instagram-graph-api/

