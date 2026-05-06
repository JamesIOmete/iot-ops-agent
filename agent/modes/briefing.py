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
    format_style = config["modes"]["briefing"]["output"]["format_style"]
    format_instruction = _FORMAT_INSTRUCTIONS.get(format_style, _FORMAT_INSTRUCTIONS["plain"])
    system_prompt = config["modes"]["briefing"]["system_prompt"].rstrip() + "\n\n" + format_instruction

    fleet_ids = ", ".join(config["fleet"]["device_ids"])
    thresholds = config["thresholds"]
    alarms = config["aws"]["cloudwatch"]["alarms"]

    user_message = f"""
Produce a fleet status briefing for the on-call engineer.

Fleet: {fleet_ids}

Check current telemetry for each device, active CloudWatch alarms
({alarms['temperature_high']}, {alarms['device_silence']}, {alarms['dlq_depth']}),
recent excursion events (last 24h), and DLQ depth.

Normal frozen storage range: {thresholds['temperature']['frozen_min_c']}°C to {thresholds['temperature']['frozen_max_c']}°C.

Format the briefing as:
## Fleet Status: [HEALTHY / DEGRADED / CRITICAL]
## Devices Needing Attention
[device name] — [issue] — [recommended action]
## Active Alarms
[list]
## Normal Devices
[brief list]
## Action Priority
[numbered list]

Keep it scannable. The engineer has 2 minutes.
""".strip()

    return core.run(user_message=user_message, system_prompt=system_prompt)
