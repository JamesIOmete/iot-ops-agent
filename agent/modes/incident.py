from pathlib import Path

import yaml

from agent.core import AgentCore


def load_runbook(runbook_id: str, config_dir: str = "config") -> dict:
    path = Path(config_dir) / "runbooks" / f"{runbook_id}.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def _format_runbook(runbook: dict) -> str:
    lines = [
        f"Runbook: {runbook['name']}",
        f"Trigger: {runbook.get('trigger_alarm', 'manual')}",
        f"Description: {runbook['description'].strip()}",
        "",
        "Steps:",
    ]
    for i, step in enumerate(runbook["steps"], 1):
        tools = ", ".join(step["tools"])
        lines.append(f"  {i}. {step['name']}")
        lines.append(f"     Tools: {tools}")
        lines.append(f"     Hypothesis: {step['hypothesis']}")
        lines.append(f"     Description: {step['description'].strip()}")
        lines.append("")
    return "\n".join(lines)


def run(
    config: dict, core: AgentCore, runbook_id: str, device_id: str = None
) -> dict:
    runbook = load_runbook(runbook_id)
    runbook_text = _format_runbook(runbook)

    system_prompt = config["modes"]["incident"]["system_prompt"]
    thresholds = config["thresholds"]
    device_context = f"Triggered for device: {device_id}" if device_id else "Device not yet identified — use list_fleet_devices to find affected device."

    user_message = f"""
An alarm has triggered incident response.

{device_context}

{runbook_text}
Temperature thresholds for context:
- Frozen storage normal range: {thresholds['temperature']['frozen_min_c']}°C to {thresholds['temperature']['frozen_max_c']}°C
- Excursion alarm threshold: above {thresholds['temperature']['excursion_high_frozen_c']}°C
- Silence threshold: {thresholds['connectivity']['silence_threshold_minutes']} minutes without heartbeat
- Escalation confidence threshold: {config['escalation']['confidence_threshold']}

Blocked remediation keywords (escalate instead): {', '.join(config['escalation']['never_auto_remediate'])}

Work through the runbook steps methodically. State your confidence level (0.0–1.0) after
each step. If confidence drops below {config['escalation']['confidence_threshold']} or your
recommended action matches a blocked keyword, publish an SNS escalation instead of acting.
If a sustained excursion is confirmed with sufficient confidence, create a GitHub issue to
track the incident.
""".strip()

    return core.run(user_message=user_message, system_prompt=system_prompt)
