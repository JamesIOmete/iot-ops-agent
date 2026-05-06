# Tool Registry

All tool permissions are defined in `config/config.yaml` under `tool_permissions`.
This document must stay in sync with that file — update both together.

## Permission Tiers

| Tier | Description |
|------|-------------|
| R | Read-only. No side effects. Safe in any mode. |
| W | Write action. Requires `allow_write_actions: true` AND mode permission. |

## Tool Permissions by Mode

| Tool | Watchdog | Incident | Briefing | Tier | AWS Service |
|------|:--------:|:--------:|:--------:|------|-------------|
| `get_device_telemetry` | ✓ | ✓ | ✓ | R | DynamoDB |
| `list_fleet_devices` | ✓ | ✓ | ✓ | R | DynamoDB |
| `get_excursion_events` | ✓ | ✓ | ✓ | R | DynamoDB |
| `get_cloudwatch_alarm_state` | ✓ | ✓ | ✓ | R | CloudWatch |
| `query_cloudwatch_logs` | ✓ | ✓ | ✗ | R | CloudWatch Logs |
| `get_dlq_depth` | ✓ | ✓ | ✓ | R | SQS |
| `get_device_shadow` | ✗ | ✓ | ✗ | R | IoT Core (Shadow) |
| `create_github_issue` | ✗ | ✓* | ✗ | W | GitHub API |
| `publish_sns_escalation` | ✗ | ✓* | ✗ | W | SNS |

`✓*` = permitted in mode AND requires `--allow-write` flag at runtime.

## Tool Descriptions

### `get_device_telemetry`
Retrieves current telemetry snapshot for a single device from DynamoDB. Returns temperature, humidity, battery level, GPS coordinates, compressor status, door status, RSSI, and last heartbeat timestamp.

**Mock fixture:** `tests/fixtures/get_device_telemetry_{device_id}.json`
Falls back to `tests/fixtures/get_device_telemetry.json` for unknown device IDs.

### `list_fleet_devices`
Scans the devices DynamoDB table and returns all registered fleet devices with their type, cargo type, firmware version, connection status, and last heartbeat.

**Mock fixture:** `tests/fixtures/list_fleet_devices.json`

### `get_excursion_events`
Queries the excursions DynamoDB table for temperature excursion events for a given device within a time window (default 24 hours). An excursion is defined as a temperature reading that crossed a configured alarm threshold.

**Mock fixture:** `tests/fixtures/get_excursion_events_{device_id}.json`
Falls back to `tests/fixtures/get_excursion_events.json` (no events).

### `get_cloudwatch_alarm_state`
Calls `describe_alarms` on CloudWatch and returns the current state (ALARM / OK / INSUFFICIENT_DATA) with the state reason and timestamp of last state change.

**Mock fixture:** `tests/fixtures/get_cloudwatch_alarm_state.json`
Mock behavior: looks up the alarm by name within the fixture's `alarms` list. Returns `OK` for unknown alarm names.

### `query_cloudwatch_logs`
Runs a CloudWatch Logs Insights query and polls for results (live: up to 30 seconds). Useful for checking device-level error logs that would indicate sensor malfunction vs genuine environmental events.

Not available in briefing mode — kept out to limit token cost on routine status queries.

**Mock fixture:** `tests/fixtures/query_cloudwatch_logs.json`

### `get_dlq_depth`
Calls `get_queue_attributes` on SQS to retrieve the approximate number of visible and in-flight messages in a Dead Letter Queue. High DLQ depth indicates the IoT rules pipeline is failing to process device telemetry.

**Mock fixture:** `tests/fixtures/get_dlq_depth.json`

### `get_device_shadow`
Retrieves the AWS IoT Device Shadow via the IoT Data Plane API. Returns the full shadow document: desired state, reported state, delta, and metadata timestamps. Available in incident mode only — used to confirm device connectivity and compare desired vs reported temperature setpoint during excursion investigation.

**Mock fixture:** `tests/fixtures/get_device_shadow_{device_id}.json`
Falls back to `tests/fixtures/get_device_shadow.json`.

### `create_github_issue` (Write)
Creates a GitHub issue in the configured incident tracking repository. Used to create a persistent record for confirmed incidents that need human follow-up but are not urgent enough to page on-call immediately.

Requires `--allow-write` at the CLI and `allow_write_actions: true` in `config.yaml` for the incident mode.

**Mock fixture:** `tests/fixtures/create_github_issue.json`
**Environment variable:** `GITHUB_TOKEN`

### `publish_sns_escalation` (Write)
Publishes a structured escalation notification to an SNS topic. Used when: confidence is below threshold, recommended action matches a `never_auto_remediate` keyword, or the runbook explicitly requires escalation. This is the primary mechanism for paging on-call.

Requires `--allow-write` at the CLI and `allow_write_actions: true` in `config.yaml` for the incident mode.

**Mock fixture:** `tests/fixtures/publish_sns_escalation.json`
**AWS resource:** configured in `config.yaml` → `aws.sns.escalation_topic_arn`

## Adding a New Tool

1. Add the implementation function to `agent/tools.py` with mock and live branches.
2. Add the tool schema to `TOOL_SCHEMAS` in `agent/tools.py`.
3. Register the function in `TOOL_REGISTRY` in `agent/core.py`.
4. Add permission entries to `config/config.yaml` → `tool_permissions`.
5. Create fixture file(s) in `tests/fixtures/`.
6. Add at least one test in `tests/test_tools.py`.
7. Update this file.

Do not modify `docs/tool-registry.md` and `config/config.yaml` independently — they must stay in sync.
