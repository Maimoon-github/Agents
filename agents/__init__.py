"""
agents/__init__.py
Ensures the Celery application is instantiated before any worker or Django management
command processes @shared_task decorators in social_agent.tasks.
"""
# This import is required so that the shared_task decorator in social_agent.tasks
# correctly uses the configured Celery app from celery_config.py rather than creating
# an implicit default app. Without this, Celery workers cannot find registered tasks.
from .celery_config import app as celery_app  # noqa: F401

__all__ = ("celery_app",)
