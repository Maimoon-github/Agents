"""
social_agent/guardrails/__init__.py
Unified exports for the defense-in-depth safety, evaluation, and self-healing subsystem.
"""
from .safety import (
    SafetyGuardrail,
    SecurityScanResult,
)
from .evaluators import (
    LLMJudgeEvaluator,
    MetricScore,
    AuditEvaluation,
)
from .self_healing import (
    SelfHealingManager,
    ErrorCategory,
    RemediationAction,
    RemediationDirective,
)

__all__ = [
    "SafetyGuardrail",
    "SecurityScanResult",
    "LLMJudgeEvaluator",
    "MetricScore",
    "AuditEvaluation",
    "SelfHealingManager",
    "ErrorCategory",
    "RemediationAction",
    "RemediationDirective",
]