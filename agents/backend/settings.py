"""
Django settings for the Autonomous Multi-Agent Social Media Architecture.
Integrates PostgreSQL via DATABASE_URL, Redis-backed Celery, structured logging,
and optional OpenTelemetry auto-instrumentation via environment variables.
"""
import os
import logging
from pathlib import Path

# ── Environment loading ───────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Core Django ───────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-(unf*(*=i_7vm0j*pjc3(lt#5@88x41%am!y+!v(vn7a36f8l_"
)

DEBUG = os.environ.get("DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "*").split(",") if h.strip()]

# ── Application definition ────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "corsheaders",
    # Local
    "social_agent.apps.SocialAgentConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "backend.wsgi.application"
ASGI_APPLICATION = "backend.asgi.application"

# ── Database ──────────────────────────────────────────────────────────────
# Primary: PostgreSQL from DATABASE_URL; fallback: SQLite for local dev.
DATABASE_URL = os.environ.get("DATABASE_URL")
POSTGRES_POOL_URL = os.environ.get("POSTGRES_POOL_URL")

if DATABASE_URL:
    try:
        import dj_database_url  # type: ignore
        DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}
    except ImportError:
        # Manually parse postgres:// URL without external dependency
        import re
        _m = re.match(r"postgres(?:ql)?://([^:]+):([^@]+)@([^/:]+)(?::(\d+))?/(.+)", DATABASE_URL)
        if _m:
            DATABASES = {
                "default": {
                    "ENGINE": "django.db.backends.postgresql",
                    "NAME": _m.group(5),
                    "USER": _m.group(1),
                    "PASSWORD": _m.group(2),
                    "HOST": _m.group(3),
                    "PORT": _m.group(4) or "5432",
                    "CONN_MAX_AGE": 600,
                    "OPTIONS": {"sslmode": "prefer"},
                }
            }
        else:
            DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

# ── Celery ────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = os.environ.get("TIME_ZONE", "Asia/Karachi")
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_SOFT_TIME_LIMIT = 600   # 10 min warning
CELERY_TASK_TIME_LIMIT = 900        # 15 min hard kill
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # Prevent premature task prefetching for long-running graph tasks
CELERY_ACKS_LATE = True             # Re-queue task if worker crashes mid-execution

# ── Django REST Framework ─────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "120/min",
    },
}

# ── CORS ──────────────────────────────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if o.strip()
]

# ── Platform Credentials ──────────────────────────────────────────────────
PLATFORM_CREDENTIALS = {
    "tiktok": {
        "client_key": os.environ.get("TIKTOK_CLIENT_KEY", ""),
        "client_secret": os.environ.get("TIKTOK_CLIENT_SECRET", ""),
        "redirect_uri": os.environ.get("TIKTOK_REDIRECT_URI", "https://yourdomain.com/api/auth/callback/tiktok/"),
        "access_token": os.environ.get("TIKTOK_ACCESS_TOKEN", ""),
        "refresh_token": os.environ.get("TIKTOK_REFRESH_TOKEN", ""),
        "scopes": ["video.publish", "video.upload", "user.info.basic"],
    },
    "x_twitter": {
        "client_id": os.environ.get("X_CLIENT_ID", ""),
        "client_secret": os.environ.get("X_CLIENT_SECRET", ""),
        "redirect_uri": os.environ.get("X_REDIRECT_URI", "https://yourdomain.com/api/auth/callback/x/"),
        "bearer_token": os.environ.get("X_BEARER_TOKEN") or os.environ.get("TWITTER_BEARER_TOKEN", ""),
        "access_token": os.environ.get("X_ACCESS_TOKEN") or os.environ.get("TWITTER_ACCESS_TOKEN", ""),
        "refresh_token": os.environ.get("X_REFRESH_TOKEN", ""),
        "scopes": ["tweet.read", "tweet.write", "users.read", "offline.access"],
    },
    "instagram": {
        "app_id": os.environ.get("META_APP_ID", ""),
        "app_secret": os.environ.get("META_APP_SECRET", ""),
        "redirect_uri": os.environ.get("META_REDIRECT_URI", "https://yourdomain.com/api/auth/callback/meta/"),
        "access_token": os.environ.get("INSTAGRAM_ACCESS_TOKEN", ""),
        "user_id": os.environ.get("INSTAGRAM_USER_ID", ""),
        "scopes": ["instagram_basic", "instagram_content_publish"],
    },
    "facebook": {
        "app_id": os.environ.get("META_APP_ID", ""),
        "app_secret": os.environ.get("META_APP_SECRET", ""),
        "redirect_uri": os.environ.get("META_REDIRECT_URI", "https://yourdomain.com/api/auth/callback/meta/"),
        "page_access_token": os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", ""),
        "page_id": os.environ.get("FACEBOOK_PAGE_ID", ""),
        "scopes": ["pages_manage_posts", "pages_read_engagement", "instagram_basic", "instagram_content_publish"],
    },
}

# ── MCP Server Endpoints ──────────────────────────────────────────────────
MCP_SERVER_URLS = {
    "x_twitter": os.environ.get("MCP_X_CONNECTOR_URL", "http://127.0.0.1:8001"),
    "instagram": os.environ.get("MCP_INSTAGRAM_CONNECTOR_URL", "http://127.0.0.1:8002"),
    "tiktok": os.environ.get("MCP_TIKTOK_CONNECTOR_URL", "http://127.0.0.1:8003"),
    "facebook": os.environ.get("MCP_FACEBOOK_CONNECTOR_URL", "http://127.0.0.1:8004"),
    "web_search": os.environ.get("MCP_WEB_SEARCH_URL", "http://127.0.0.1:8005"),
}

# ── Password validation ───────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ── Internationalisation ──────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Karachi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Structured Logging ────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "logging.Formatter",
            "fmt": '{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}',
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
        "verbose": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "social_agent": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "celery": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

# ── Security Headers (Production) ─────────────────────────────────────────
if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
