"""
social_agent/views.py
Django REST Framework views for campaign execution, human review/resumption, and platform webhooks.
"""
import uuid
import logging
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.generics import RetrieveAPIView, ListAPIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.pagination import PageNumberPagination

from social_agent.models import SocialCampaign, AgentAuditLog
from social_agent.serializers import (
    CampaignCreateSerializer,
    HITLApprovalSerializer,
    CampaignDetailSerializer,
    AgentAuditLogSerializer,
)
from social_agent.tasks import run_campaign_workflow_task, resume_hitl_workflow_task

logger = logging.getLogger("social_agent")


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class TriggerCampaignView(APIView):
    """
    POST /api/campaigns/
    Triggers a new multi-agent social media workflow with transaction-safe Celery dispatch.
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = CampaignCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        prompt = validated["prompt"]
        platforms = validated.get("platforms", ["x_twitter", "instagram"])
        title = validated.get("title") or f"Campaign: {prompt[:30]}..."
        thread_id = f"thread_{uuid.uuid4()}"

        with transaction.atomic():
            campaign = SocialCampaign.objects.create(
                title=title,
                raw_prompt=prompt,
                target_platforms=platforms,
                langgraph_thread_id=thread_id,
                status="PENDING"
            )
            # Guarantee DB commit prior to Celery worker pickup to prevent ObjectDoesNotExist race
            transaction.on_commit(lambda: run_campaign_workflow_task.delay(str(campaign.id)))

        logger.info("Created campaign '%s' [Thread: %s]. Enqueued Celery task.", campaign.id, thread_id)
        return Response(
            {
                "status": "initiated",
                "campaign_id": str(campaign.id),
                "thread_id": campaign.langgraph_thread_id,
                "workflow_status": campaign.status
            },
            status=status.HTTP_201_CREATED
        )


class HITLApprovalView(APIView):
    """
    POST /api/campaigns/<uuid:id>/approve/
    Resumes an interrupted workflow at the HITL gate with human review verdict and edits.
    """
    permission_classes = [AllowAny]

    def post(self, request, id, *args, **kwargs):
        campaign = get_object_or_404(SocialCampaign, id=id)

        if campaign.status != "AWAITING_APPROVAL":
            return Response(
                {"error": f"Campaign is not awaiting approval (Current status: '{campaign.status}')."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = HITLApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        approved = data["approved"]
        notes = data.get("notes", "")
        modified_content = data.get("modified_content", {})

        with transaction.atomic():
            campaign.status = "RUNNING"
            campaign.save(update_fields=["status", "updated_at"])
            transaction.on_commit(
                lambda: resume_hitl_workflow_task.delay(
                    str(campaign.id),
                    approved,
                    notes,
                    modified_content
                )
            )

        logger.info("HITL decision submitted for campaign '%s': Approved=%s", campaign.id, approved)
        return Response(
            {
                "status": "resumed",
                "campaign_id": str(campaign.id),
                "decision": "APPROVED" if approved else "REJECTED"
            },
            status=status.HTTP_200_OK
        )


class CampaignDetailView(RetrieveAPIView):
    """
    GET /api/campaigns/<uuid:id>/
    Retrieves campaign status, generated posts, and evaluation metrics with prefetch optimization.
    """
    permission_classes = [AllowAny]
    serializer_class = CampaignDetailSerializer
    lookup_field = "id"

    def get_queryset(self):
        return SocialCampaign.objects.prefetch_related("posts", "audit_logs")


class CampaignAuditLogView(ListAPIView):
    """
    GET /api/campaigns/<uuid:id>/audit/
    Retrieves paginated audit log traces for a specific campaign.
    """
    permission_classes = [AllowAny]
    serializer_class = AgentAuditLogSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        campaign_id = self.kwargs.get("id")
        return AgentAuditLog.objects.filter(campaign_id=campaign_id).order_by("-timestamp")


class PlatformWebhookView(APIView):
    """
    POST /api/webhooks/<str:platform>/
    Ingests asynchronous engagement/mention webhooks from social media platforms.
    """
    permission_classes = [AllowAny]

    def post(self, request, platform, *args, **kwargs):
        logger.info("Received inbound webhook event from platform '%s'", platform)
        return Response({"status": "received", "platform": platform}, status=status.HTTP_200_OK)