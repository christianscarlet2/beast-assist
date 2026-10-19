"""OpenTelemetry tracing: one span per tool call, so agent runs can be traced tool by tool.

OTEL_EXPORTER_OTLP_ENDPOINT set -> OTLP/HTTP (Jaeger, Azure Monitor, Grafana...); otherwise spans
are dropped and only the JSON log line remains."""
import json
import logging
import os
import sys
import time

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_log = logging.getLogger("beast.toolcall")


def setup(service: str):
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    if not _log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(message)s"))
        _log.addHandler(h)
        _log.setLevel(logging.INFO)
    return trace.get_tracer(service)


def log_call(**fields):
    """One JSON line per tool call: the tool-call analysis feed (duration, outcome, skill, caller)."""
    span = trace.get_current_span().get_span_context()
    if span.is_valid:
        fields["trace_id"] = format(span.trace_id, "032x")
    fields["ts"] = round(time.time(), 3)
    _log.info(json.dumps(fields, default=str))
