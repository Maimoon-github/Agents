"""
social_agent/apps.py
SocialAgentConfig application configuration and startup environment validation.
"""
import os
import logging
from django.apps import AppConfig

logger = logging.getLogger("social_agent")


class SocialAgentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "social_agent"
    verbose_name = "Autonomous Social Agent Subsystem"

    def ready(self):
        """Executes on application startup to verify environment and initialize directories."""
        # Ensure local vector store persistence directory exists
        chroma_dir = os.environ.get("CHROMA_PERSIST_DIRECTORY", "/var/data/chromadb")
        try:
            os.makedirs(chroma_dir, exist_ok=True)
        except Exception as e:
            logger.warning("Could not create Chroma persistence directory at %s: %s", chroma_dir, e)

        # Non-blocking environment validation
        if not os.environ.get("CELERY_BROKER_URL"):
            logger.info("CELERY_BROKER_URL not explicitly set; defaulting to redis://127.0.0.1:6379/0.")