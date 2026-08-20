"""
social_agent/apps.py
SocialAgentConfig application configuration.
Bootstraps Chroma persistence directory, validates the environment, and
initializes the OpenTelemetry tracer on Django application startup.
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
        """Executes once on application start-up (both server and Celery workers)."""

        # 1. Ensure ChromaDB vector store persistence directory is provisioned
        chroma_dir = os.environ.get("CHROMA_PERSIST_DIRECTORY", "/var/data/chromadb")
        try:
            os.makedirs(chroma_dir, exist_ok=True)
            logger.debug("ChromaDB persistence directory verified: %s", chroma_dir)
        except Exception as exc:
            logger.warning("Could not create Chroma persistence directory at %s: %s", chroma_dir, exc)

        # 2. Non-blocking environment configuration validation
        _required_warnings = {
            "CELERY_BROKER_URL": "Redis broker not set; defaulting to redis://127.0.0.1:6379/0",
            "DJANGO_SECRET_KEY": "WARNING: Using insecure default SECRET_KEY in production!",
        }
        for key, msg in _required_warnings.items():
            if not os.environ.get(key):
                logger.info("%s — %s", key, msg)

        # 3. Initialize OpenTelemetry tracing provider (idempotent)
        _otel_enabled = os.environ.get("OPENTELEMETRY_ENABLED", "false").lower() in ("true", "1", "yes")
        if _otel_enabled:
            try:
                from social_agent.telemetry.tracing import setup_telemetry
                setup_telemetry(
                    service_name="social_agent",
                    otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
                    langfuse_public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
                    langfuse_secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
                    langfuse_host=os.environ.get("LANGFUSE_HOST"),
                )
                logger.info("OpenTelemetry tracing initialized via apps.ready()")

                # Auto-instrument Django HTTP requests if OTel instrumentation package is available
                try:
                    from opentelemetry.instrumentation.django import DjangoInstrumentor
                    DjangoInstrumentor().instrument()
                    logger.debug("Django OTel auto-instrumentation active.")
                except ImportError:
                    pass

            except Exception as otel_err:
                logger.warning("OpenTelemetry setup failed in apps.ready(): %s", otel_err)

        logger.info("SocialAgentConfig.ready() completed successfully.")