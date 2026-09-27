"""
AI Incident Copilot
--------------------
Receives Alertmanager webhooks, pulls supporting context from Prometheus
and Loki, asks Claude to summarize the likely root cause in plain English,
and posts the result to Slack.

This is the "AI that resolves threats with minimal human intervention"
piece of the platform - deliberately mirroring CloudSEK's own product
pitch, applied to internal platform reliability instead of external
threat detection.
"""

import os
import logging

import requests
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ai-copilot")

app = Flask(__name__)

PROM_URL = os.environ.get(
    "PROMETHEUS_URL", "http://kube-prometheus-kube-prome-prometheus.monitoring:9090"
)
LOKI_URL = os.environ.get("LOKI_URL", "http://loki.monitoring:3100")
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def query_prometheus_context(alertname: str) -> str:
    """Pull the live alert series for this alertname as supporting evidence."""
    try:
        query = f'ALERTS{{alertname="{alertname}"}}'
        resp = requests.get(
            f"{PROM_URL}/api/v1/query", params={"query": query}, timeout=5
        )
        resp.raise_for_status()
        return str(resp.json().get("data", {}).get("result", []))[:1500]
    except Exception as exc:  # noqa: BLE001 - best-effort context, never fatal
        log.warning("Prometheus query failed: %s", exc)
        return "(no Prometheus context available)"


def query_loki_context(namespace: str) -> str:
    """Pull the most recent error-level logs from the affected namespace."""
    try:
        query = f'{{namespace="{namespace}"}} |= "error"'
        resp = requests.get(
            f"{LOKI_URL}/loki/api/v1/query_range",
            params={"query": query, "limit": 20},
            timeout=5,
        )
        resp.raise_for_status()
        return str(resp.json().get("data", {}).get("result", []))[:1500]
    except Exception as exc:  # noqa: BLE001
        log.warning("Loki query failed: %s", exc)
        return "(no Loki context available)"


def ask_claude(alert_summary: str, prom_context: str, loki_context: str) -> str:
    prompt = f"""You are an SRE incident copilot for a Kubernetes platform. \
An alert just fired.

Alert details:
{alert_summary}

Prometheus context:
{prom_context}

Recent Loki logs (may be empty):
{loki_context}

In 3-4 short, plain-English sentences: explain what likely happened and \
suggest one concrete next step. No preamble, no markdown headers."""

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(block.get("text", "") for block in data.get("content", []))


def post_to_slack(alertname: str, severity: str, summary: str) -> None:
    icon = "🔴" if severity == "critical" else "🟡"
    requests.post(
        SLACK_WEBHOOK_URL,
        json={
            "text": (
                f"{icon} *AI Incident Copilot* — `{alertname}`\n"
                f"{summary}"
            )
        },
        timeout=5,
    )


@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json(force=True, silent=True) or {}
    alerts = payload.get("alerts", [])
    log.info("Received %d alert(s)", len(alerts))

    for alert in alerts:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alertname = labels.get("alertname", "UnknownAlert")
        namespace = labels.get("namespace", "default")
        severity = labels.get("severity", "warning")

        alert_summary = (
            f"Name: {alertname}\n"
            f"Namespace: {namespace}\n"
            f"Severity: {severity}\n"
            f"Summary: {annotations.get('summary', '')}\n"
            f"Description: {annotations.get('description', '')}"
        )

        prom_context = query_prometheus_context(alertname)
        loki_context = query_loki_context(namespace)

        try:
            ai_summary = ask_claude(alert_summary, prom_context, loki_context)
        except Exception as exc:  # noqa: BLE001
            log.error("Claude API call failed: %s", exc)
            ai_summary = (
                f"(AI summary unavailable right now: {exc}. "
                f"Raw alert: {annotations.get('summary', alertname)})"
            )

        post_to_slack(alertname, severity, ai_summary)

    return jsonify({"status": "ok", "processed": len(alerts)})


@app.route("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
