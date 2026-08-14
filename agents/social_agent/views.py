"""
social_agent/views.py
Django REST Framework views for triggering workflows and handling human approval.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from social_agent.models import SocialCampaign
from social_agent.tasks import run_campaign_workflow_task, resume_hitl_workflow_task
import uuid


class TriggerCampaignView(APIView):
    def post(self, request):
        prompt = request.data.get('prompt')
        platforms = request.data.get('platforms', ['x_twitter', 'instagram'])
        
        if not prompt:
            return Response({"error": "Missing 'prompt'"}, status=status.HTTP_400_BAD_REQUEST)
            
        campaign = SocialCampaign.objects.create(
            title=request.data.get('title', f"Campaign {prompt[:20]}..."),
            raw_prompt=prompt,
            target_platforms=platforms,
            langgraph_thread_id=f"thread_{uuid.uuid4()}",
            status='PENDING'
        )
        
        # Trigger Celery Task
        run_campaign_workflow_task.delay(str(campaign.id))
        
        return Response({
            "status": "initiated",
            "campaign_id": str(campaign.id),
            "thread_id": campaign.langgraph_thread_id
        }, status=status.HTTP_201_CREATED)


class HITLApprovalView(APIView):
    def post(self, request, campaign_id):
        campaign = get_object_or_404(SocialCampaign, id=campaign_id)
        if campaign.status != 'AWAITING_APPROVAL':
            return Response({"error": f"Campaign is not awaiting approval (Current: {campaign.status})"}, status=status.HTTP_400_BAD_REQUEST)
            
        approved = request.data.get('approved', False)
        notes = request.data.get('notes', '')
        modified_content = request.data.get('modified_content', {})
        
        # Resume workflow via Celery
        resume_hitl_workflow_task.delay(str(campaign.id), approved, notes, modified_content)
        
        return Response({
            "status": "resumed",
            "decision": "APPROVED" if approved else "REJECTED"
        }, status=status.HTTP_200_OK)
