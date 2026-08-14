"""
social_agent/telemetry/tracing.py
OpenTelemetry and Langfuse distributed tracing setup, span lifecycle, and W3C context propagation.
"""
import os
import time
import base64
import logging
import contextlib
from typing import Dict, Any, Optional, AsyncIterator

logger = logging.getLogger("social_agent.telemetry")

# OpenTelemetry imports with graceful no-op fallbacks
try:
    from opentelemetry import trace, propagate
    from opentelemetry.trace import Status, StatusCode, Span
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False
    trace = None
    propagate = None


class NoOpSpan:
    """Fallback no-op span when OpenTelemetry is unconfigured or unavailable."""
    def set_attribute(self, key: str, value: Any): pass
    def set_status(self, status: Any, description: Optional[str] = None): pass
    def record_exception(self, exception: Exception): pass
    def end(self): pass


class NoOpTracer:
    """Fallback no-op tracer."""
    def start_as_current_span(self, name: str, *args, **kwargs):
        @contextlib.contextmanager
        def _noop_gen():
            yield NoOpSpan()
        return _noop_gen()


_TRACER_INITIALIZED = False


def setup_telemetry(
    service_name: str = "social_agent",
    otlp_endpoint: Optional[str] = None,
    langfuse_public_key: Optional[str] = None,
    langfuse_secret_key: Optional[str] = None,
    langfuse_host: Optional[str] = None
) -> None:
    """
    Initializes the OpenTelemetry TracerProvider with OTLP HTTP exporter configured for Langfuse or local OTLP collector.
    Safe and idempotent: multiple calls do not overwrite active provider.
    """
    global _TRACER_INITIALIZED
    if _TRACER_INITIALIZED or not HAS_OTEL:
        return

    try:
        resource = Resource.create({"service.name": service_name, "service.version": "2026.1"})
        provider = TracerProvider(resource=resource)

        # 1. Resolve Target Endpoints and Authentication
        pk = langfuse_public_key or os.environ.get("LANGFUSE_PUBLIC_KEY")
        sk = langfuse_secret_key or os.environ.get("LANGFUSE_SECRET_KEY")
        host = (langfuse_host or os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")).rstrip("/")

        headers = {}
        target_endpoint = otlp_endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")

        if pk and sk:
            # Langfuse OTLP v1/traces endpoint with Basic Auth
            auth_str = f"{pk}:{sk}"
            b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
            headers["Authorization"] = f"Basic {b64_auth}"
            target_endpoint = f"{host}/api/public/otel/v1/traces"
        elif not target_endpoint:
            # Default local OTLP collector HTTP port
            target_endpoint = "http://localhost:4318/v1/traces"

        # 2. Attach Non-Blocking Batch Processor
        exporter = OTLPSpanExporter(
            endpoint=target_endpoint,
            headers=headers,
            timeout=5.0
        )
        processor = BatchSpanProcessor(
            exporter,
            max_export_batch_size=512,
            schedule_delay_millis=5000
        )
        provider.add_span_processor(processor)

        trace.set_tracer_provider(provider)
        _TRACER_INITIALIZED = True
        logger.info("OpenTelemetry tracing initialized successfully (Target: %s)", target_endpoint)

    except Exception as e:
        logger.warning("Failed to initialize OpenTelemetry TracerProvider (%s). Continuing without tracing.", e)


def get_tracer(module_name: str = "social_agent") -> Any:
    """Returns an active Tracer instance or NoOpTracer."""
    if HAS_OTEL and _TRACER_INITIALIZED and trace:
        return trace.get_tracer(module_name)
    return NoOpTracer()


@contextlib.asynccontextmanager
async def trace_span(
    name: str,
    attributes: Optional[Dict[str, Any]] = None
) -> AsyncIterator[Any]:
    """
    Asynchronous context manager creating a correlated OpenTelemetry span with domain attributes.

    Args:
        name: Span identifier (e.g. 'node.plan_research', 'tool.post_x_tweet').
        attributes: Dictionary of attributes to attach to the span.

    Yields:
        Active Span instance.
    """
    tracer = get_tracer("social_agent")
    t0 = time.perf_counter()
    
    if not HAS_OTEL or not _TRACER_INITIALIZED or isinstance(tracer, NoOpTracer):
        span = NoOpSpan()
        try:
            yield span
        finally:
            pass
        return

    with tracer.start_as_current_span(name) as span:
        # Inject Standardized Domain Attributes
        if attributes:
            for k, v in attributes.items():
                if v is not None:
                    attr_key = f"social_agent.{k}" if not k.startswith("social_agent.") else k
                    span.set_attribute(attr_key, str(v) if not isinstance(v, (int, float, bool)) else v)

        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            span.set_attribute("social_agent.duration_ms", round(elapsed_ms, 2))
            if elapsed_ms > 15.0:
                logger.debug("Span '%s' execution time: %.2f ms", name, elapsed_ms)


def inject_trace_context(carrier: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Injects W3C TraceContext headers into a dictionary carrier for Celery task propagation."""
    out_carrier = carrier if carrier is not None else {}
    if HAS_OTEL and propagate:
        propagate.inject(out_carrier)
    return out_carrier


def extract_trace_context(carrier: Dict[str, str]) -> Any:
    """Extracts W3C TraceContext headers from a dictionary carrier."""
    if HAS_OTEL and propagate:
        return propagate.extract(carrier)
    return None