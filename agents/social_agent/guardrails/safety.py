"""
social_agent/guardrails/safety.py
Pre-execution input sanitization, PII redaction, prompt injection defense, and Llama-Guard 3 hook.
"""
import re
import logging
from typing import Dict, Any, List, Tuple, Optional, Literal
import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SecurityScanResult(BaseModel):
    """Encapsulates the verdict and sanitized output of a security scan."""
    is_safe: bool = Field(..., description="Whether the payload is safe to process.")
    risk_category: Literal[
        "NONE",
        "PROMPT_INJECTION",
        "PII_LEAKAGE",
        "PROHIBITED_KEYWORD",
        "TOXICITY",
        "MALICIOUS_PAYLOAD"
    ] = Field(default="NONE", description="Classified risk type.")
    sanitized_text: str = Field(..., description="Sanitized text with PII redacted or safe content.")
    detected_violations: List[str] = Field(default_factory=list, description="Specific policy violations.")
    confidence_score: float = Field(default=1.0, description="Classifier certainty (0.0 - 1.0).")


class SafetyGuardrail:
    """
    Multi-layered defense-in-depth safety engine implementing deterministic regex rules,
    PII redaction, prompt injection detection, and Llama-Guard 3 classification.
    """
    def __init__(
        self,
        prohibited_keywords: Optional[List[str]] = None,
        llama_guard_endpoint: str = "http://127.0.0.1:11434/v1"
    ):
        self.prohibited_keywords = [
            k.lower() for k in (prohibited_keywords or ["revolutionize", "synergy", "disruptive", "game-changer"])
        ]
        self.llama_guard_endpoint = llama_guard_endpoint.rstrip("/")
        
        # Deterministic Regex Patterns
        self._email_pattern = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
        self._phone_pattern = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
        self._credit_card_pattern = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
        self._secret_pattern = re.compile(r"(?i)(?:api[_-]?key|secret|token|bearer|password|private[_-]?key)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{16,})['\"]?")
        
        # Injection Markers (Case-Insensitive)
        self._injection_patterns = [
            re.compile(r"(?i)\bignore\s+(?:all\s+)?previous\s+instructions\b"),
            re.compile(r"(?i)\bsystem\s+override\b"),
            re.compile(r"(?i)\bjailbreak\b"),
            re.compile(r"(?i)\bdeveloper\s+mode\b"),
            re.compile(r"(?i)\bDAN\s+mode\b"),
            re.compile(r"(?i)\bdisregard\s+(?:all\s+)?prior\s+prompts\b"),
            re.compile(r"(?i)\breveal\s+(?:the\s+)?system\s+prompt\b"),
            re.compile(r"(?i)\boutput\s+(?:the\s+)?raw\s+instructions\b"),
        ]

    def _luhn_check(self, card_num: str) -> bool:
        """Validates potential credit card numbers with Luhn checksum algorithm."""
        digits = [int(c) for c in card_num if c.isdigit()]
        if len(digits) < 13 or len(digits) > 19:
            return False
        checksum = 0
        reverse_digits = digits[::-1]
        for i, d in enumerate(reverse_digits):
            if i % 2 == 1:
                d = d * 2
                if d > 9:
                    d -= 9
            checksum += d
        return checksum % 10 == 0

    def sanitize_and_redact(self, text: str) -> Tuple[str, List[str]]:
        """
        Redacts PII (email, phone, credit card, secrets) from input text.
        
        Returns:
            Tuple of (sanitized_string, list_of_detected_violations).
        """
        violations = []
        sanitized = text

        # 1. Redact Secrets & API Keys
        def _secret_repl(match):
            violations.append("Exposed API Key / Secret Token")
            return match.group(0).replace(match.group(1), "[REDACTED_SECRET]")

        sanitized = self._secret_pattern.sub(_secret_repl, sanitized)

        # 2. Redact Emails
        if self._email_pattern.search(sanitized):
            violations.append("Exposed Email Address")
            sanitized = self._email_pattern.sub("[REDACTED_EMAIL]", sanitized)

        # 3. Redact Phone Numbers
        if self._phone_pattern.search(sanitized):
            violations.append("Exposed Phone Number")
            sanitized = self._phone_pattern.sub("[REDACTED_PHONE]", sanitized)

        # 4. Redact Valid Credit Cards (with Luhn check)
        for match in self._credit_card_pattern.finditer(sanitized):
            raw_card = match.group(0)
            if self._luhn_check(raw_card):
                violations.append("Exposed Credit Card Number")
                sanitized = sanitized.replace(raw_card, "[REDACTED_CREDIT_CARD]")

        return sanitized, violations

    async def _call_llama_guard(self, text: str, role: str = "user") -> Optional[bool]:
        """
        Dispatches text to local Llama-Guard 3 endpoint.
        Returns True if safe, False if unsafe, None on connection timeout.
        """
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                endpoint = f"{self.llama_guard_endpoint}/chat/completions"
                payload = {
                    "model": "llama-guard3",
                    "messages": [{"role": role, "content": text}],
                    "temperature": 0.0
                }
                resp = await client.post(endpoint, json=payload)
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"].strip().lower()
                    if "unsafe" in content:
                        return False
                    return True
        except Exception as e:
            logger.debug("Llama-Guard 3 endpoint unreachable (%s). Using deterministic rules.", e)
        return None

    async def scan_inbound_prompt(self, raw_prompt: str) -> SecurityScanResult:
        """
        Scans incoming campaign prompts for prompt injection attacks and malicious PII.
        Zero-tolerance policy: Injection attempts immediately flag is_safe=False.
        """
        detected_violations = []

        # 1. Deterministic Injection Check
        for pattern in self._injection_patterns:
            if pattern.search(raw_prompt):
                detected_violations.append(f"Direct Prompt Injection Pattern: '{pattern.pattern}'")

        if detected_violations:
            return SecurityScanResult(
                is_safe=False,
                risk_category="PROMPT_INJECTION",
                sanitized_text=raw_prompt,
                detected_violations=detected_violations,
                confidence_score=0.99
            )

        # 2. PII Sanitization
        sanitized_text, pii_violations = self.sanitize_and_redact(raw_prompt)
        detected_violations.extend(pii_violations)

        # 3. Llama-Guard 3 Verification
        lg_safe = await self._call_llama_guard(sanitized_text, role="user")
        if lg_safe is False:
            detected_violations.append("Llama-Guard 3 Safety Policy Violation")
            return SecurityScanResult(
                is_safe=False,
                risk_category="TOXICITY",
                sanitized_text=sanitized_text,
                detected_violations=detected_violations,
                confidence_score=0.95
            )

        risk_cat = "PII_LEAKAGE" if pii_violations else "NONE"
        return SecurityScanResult(
            is_safe=True,
            risk_category=risk_cat,
            sanitized_text=sanitized_text,
            detected_violations=detected_violations,
            confidence_score=0.98 if lg_safe is not None else 0.90
        )

    def check_prohibited_terms(self, text: str) -> List[str]:
        """
        Identifies exact and lemmatized corporate buzzwords from the brand blocklist.
        """
        found_terms = []
        lower_text = text.lower()
        for keyword in self.prohibited_keywords:
            stem = keyword.rstrip("ed").rstrip("ing").rstrip("e")
            pattern = re.compile(rf"\b{re.escape(stem)}\w*\b", re.IGNORECASE)
            if pattern.search(lower_text):
                found_terms.append(keyword)
        return found_terms

    async def validate_outbound_content(self, content: str, platform: str) -> SecurityScanResult:
        """
        Scans generated multimodal copy before transmission to platform APIs.
        """
        violations = []

        # 1. PII Check
        sanitized, pii_violations = self.sanitize_and_redact(content)
        if pii_violations:
            violations.extend(pii_violations)

        # 2. Blocklist Buzzwords Check
        prohibited_matches = self.check_prohibited_terms(content)
        if prohibited_matches:
            violations.append(f"Contains prohibited buzzwords: {', '.join(prohibited_matches)}")

        # 3. Platform Constraint Validation
        if platform == "x_twitter" and len(content) > 280:
            violations.append(f"Character limit exceeded for standard X/Twitter post ({len(content)} > 280)")
        elif platform in ("instagram", "tiktok") and len(content) > 2200:
            violations.append(f"Caption limit exceeded for {platform} ({len(content)} > 2200)")

        # 4. Llama-Guard 3 Check on Assistant Output
        lg_safe = await self._call_llama_guard(content, role="assistant")
        if lg_safe is False:
            violations.append("Llama-Guard 3 Outbound Safety Policy Violation")

        is_safe = len(violations) == 0
        risk_cat = "PROHIBITED_KEYWORD" if prohibited_matches else ("PII_LEAKAGE" if pii_violations else ("TOXICITY" if lg_safe is False else "NONE"))

        return SecurityScanResult(
            is_safe=is_safe,
            risk_category=risk_cat,
            sanitized_text=sanitized,
            detected_violations=violations,
            confidence_score=0.96 if lg_safe is not None else 0.90
        )