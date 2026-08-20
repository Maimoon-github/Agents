"""
celery_config.py
Celery application factory for the Autonomous Multi-Agent Social Media Architecture.
Must be imported by agents/__init__.py so that @shared_task decorators are bound at startup.
Note: Named celery_config.py (not celery.py) to avoid shadowing the `celery` PyPI package.
"""
import os
from celery import Celery
from django.conf import settings

# Set the default Django settings module for Celery workers
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
app = Celery("social_agent_workers")

# Bind all Celery configuration from the CELERY_* namespace in Django settings
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover @shared_task decorated functions across all INSTALLED_APPS
app.autodiscover_tasks()


# ---------------------------------------------------------------------------
# Celery Beat periodic task schedule (daily cost-cap reset)
# ---------------------------------------------------------------------------
app.conf.beat_schedule = {
    "reset-daily-cost-accumulator": {
        "task": "social_agent.tasks.reset_daily_cost_accumulator_task",
        "schedule": 86400.0,   # Every 24 hours
        "options": {"expires": 3600},
    },
}
app.conf.timezone = settings.TIME_ZONE


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Heartbeat probe task for Celery worker health verification."""
    print(f"Request: {self.request!r}")
