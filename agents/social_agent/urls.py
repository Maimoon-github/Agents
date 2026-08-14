"""
social_agent/urls.py
REST API URL routing for campaigns, approvals, audit logs, and social webhooks.
"""
from django.urls import path
from social_agent.views import (
    TriggerCampaignView,
    CampaignDetailView,
    HITLApprovalView,
    CampaignAuditLogView,
    PlatformWebhookView,
)

app_name = "social_agent"

urlpatterns = [
    # Campaign Lifecycle Operations
    path("api/campaigns/", TriggerCampaignView.as_view(), name="campaign-trigger"),
    path("api/campaigns/<uuid:id>/", CampaignDetailView.as_view(), name="campaign-detail"),
    path("api/campaigns/<uuid:id>/approve/", HITLApprovalView.as_view(), name="campaign-approve"),
    path("api/campaigns/<uuid:id>/audit/", CampaignAuditLogView.as_view(), name="campaign-audit"),

    # Reactive Platform Webhooks
    path("api/webhooks/<str:platform>/", PlatformWebhookView.as_view(), name="platform-webhook"),
]