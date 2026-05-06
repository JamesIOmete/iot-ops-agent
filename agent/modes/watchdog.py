from agent.core import AgentCore


_FORMAT_INSTRUCTIONS = {
    "plain": (
        "Formatting: Use plain markdown only. Do not use emojis. "
        "Represent status with text labels: CRITICAL, DEGRADED, WARNING, OK. "
        "Use markdown headers, bold text, and bullet lists for structure."
    ),
    "emoji": (
        "Formatting: Use emojis (🚨 🔴 🟡 ✅) alongside text status labels "
        "as visual indicators to make the output scannable."
    ),
}


def run(config: dict, core: AgentCore) -> dict:
    format_style = config["modes"]["watchdog"]["output"]["format_style"]
    format_instruction = _FORMAT_INSTRUCTIONS.get(format_style, _FORMAT_INSTRUCTIONS["plain"])
    system_prompt = config["modes"]["watchdog"]["system_prompt"].rstrip() + "\n\n" + format_instruction

    fleet_ids = ", ".join(config["fleet"]["device_ids"])
    thresholds = config["thresholds"]
    alarms = config["aws"]["cloudwatch"]["alarms"]

    user_message = f"""
Execute a complete fleet health check for the cold chain IoT fleet.

Fleet devices: {fleet_ids}

Check the following for every device:
1. Current telemetry — temperature, battery, connectivity, last heartbeat
2. Excursion events in the last 24 hours
3. CloudWatch alarm states: {alarms['temperature_high']}, {alarms['device_silence']}, {alarms['dlq_depth']}
4. DLQ depth for queue: {config['aws']['sqs']['dlq_name']}

Temperature thresholds (frozen storage):
- Normal range: {thresholds['temperature']['frozen_min_c']}°C to {thresholds['temperature']['frozen_max_c']}°C
- Excursion alarm threshold: above {thresholds['temperature']['excursion_high_frozen_c']}°C

Connectivity threshold: silent if no heartbeat for {thresholds['connectivity']['silence_threshold_minutes']} minutes.
DLQ warning threshold: {thresholds['dlq']['depth_warning']} messages.

Produce a structured fleet health report with:
- Overall fleet status (HEALTHY / DEGRADED / CRITICAL)
- Devices requiring immediate attention (with reason)
- Active alarms
- Devices operating normally (brief)
- Recommended next steps
""".strip()

    return core.run(user_message=user_message, system_prompt=system_prompt)
