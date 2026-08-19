"""
Django settings for backend project.
Autonomous Multi-Agent Social Media Architecture configuration.
"""
import os
from pathlib import Path

# Try importing dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-(unf*(*=i_7vm0j*pjc3(lt#5@88x41%am!y+!v(vn7a36f8l_"
)

DEBUG = os.environ.get("DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party integrations
    "rest_framework",
    # Local application
    "social_agent.apps.SocialAgentConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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


# Database Configuration

DATABASE_URL = os.environ.get("DATABASE_URL")
POSTGRES_POOL_URL = os.environ.get("POSTGRES_POOL_URL")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Celery Broker Settings
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"


# REST Framework Configuration

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}


# ==============================================================================
# Platform Credentials & Authentication Configuration
# ==============================================================================
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


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Karachi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
