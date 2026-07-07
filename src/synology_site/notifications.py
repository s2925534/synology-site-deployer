from __future__ import annotations

from collections.abc import Callable
from typing import Any

import requests

from synology_site.config import Settings
from synology_site.output import warn

WebhookPost = Callable[..., Any]


def send_webhook_notification(
    settings: Settings,
    *,
    event: str,
    command: str,
    title: str,
    detail: str,
    post: WebhookPost = requests.post,
) -> bool:
    if not settings.notify_webhook_url:
        return False
    if not _event_enabled(settings.notify_webhook_events, event):
        return False

    message = f"[synology-site] {title}\nCommand: {command}\n{detail}"
    payload = {
        "text": message,
        "content": message,
        "event": event,
        "command": command,
    }
    try:
        response = post(settings.notify_webhook_url, json=payload, timeout=10)
        if getattr(response, "status_code", 500) >= 400:
            warn(f"Notification webhook returned HTTP {response.status_code}")
            return False
    except requests.RequestException as exc:
        warn(f"Notification webhook failed: {exc}")
        return False
    return True


def _event_enabled(configured: str, event: str) -> bool:
    events = {part.strip().lower() for part in configured.split(",") if part.strip()}
    return "all" in events or event.lower() in events
