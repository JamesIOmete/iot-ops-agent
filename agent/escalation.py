"""
All escalation decisions live here. No escalation logic in mode files or tool functions.
Escalation is a first-class outcome: it gets its own log event and a clean agent exit.
"""


def check_escalation(
    confidence: float, action_text: str, config: dict
) -> tuple[bool, str]:
    """
    Returns (should_escalate, reason).

    Fires when confidence is below the configured threshold OR when the
    recommended action contains a never_auto_remediate keyword. Both checks
    are required per the project spec — the keyword list is a hard block
    independent of confidence level.
    """
    threshold = config["escalation"]["confidence_threshold"]
    if confidence < threshold:
        return True, (
            f"confidence {confidence:.2f} is below threshold {threshold}"
        )

    action_lower = action_text.lower()
    for keyword in config["escalation"]["never_auto_remediate"]:
        if keyword.lower() in action_lower:
            return True, f"action contains blocked keyword: '{keyword}'"

    return False, ""


def build_escalation_payload(
    reason: str,
    mode: str,
    device_ids: list[str],
    confidence: float,
    summary: str,
) -> dict:
    """Structured payload passed to publish_sns_escalation and logged as an escalation event."""
    return {
        "reason": reason,
        "mode": mode,
        "device_ids": device_ids,
        "confidence": confidence,
        "summary": summary,
    }
