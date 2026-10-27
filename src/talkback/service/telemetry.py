"""OpenTelemetry for the gallery: Agent Framework spans to Application Insights (and Foundry tracing)."""

from __future__ import annotations

import os


def configure() -> bool:
    conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not conn:
        return False
    from azure.monitor.opentelemetry import configure_azure_monitor
    from agent_framework.observability import enable_instrumentation

    configure_azure_monitor(connection_string=conn, enable_live_metrics=True)
    enable_instrumentation(enable_sensitive_data=False)
    return True
