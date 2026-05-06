import copy
import pytest
import yaml
from pathlib import Path

from agent.tools import (
    create_github_issue,
    get_cloudwatch_alarm_state,
    get_device_shadow,
    get_device_telemetry,
    get_dlq_depth,
    get_excursion_events,
    list_fleet_devices,
    publish_sns_escalation,
    query_cloudwatch_logs,
)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"


@pytest.fixture
def config():
    with open(_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    cfg["runtime"]["mock_mode"] = True
    cfg["runtime"]["mode"] = "incident"
    cfg["runtime"]["allow_write_actions"] = True
    return cfg


@pytest.fixture
def config_no_write(config):
    cfg = copy.deepcopy(config)
    cfg["runtime"]["allow_write_actions"] = False
    return cfg


# --- get_device_telemetry ---

def test_get_device_telemetry_truck001(config):
    result = get_device_telemetry(config, device_id="truck-001")
    assert result["data_source"] == "mock"
    assert result["device_id"] == "truck-001"
    assert isinstance(result["temperature_c"], float)
    assert result["connectivity_status"] == "connected"


def test_get_device_telemetry_truck002_excursion(config):
    result = get_device_telemetry(config, device_id="truck-002")
    assert result["data_source"] == "mock"
    assert result["device_id"] == "truck-002"
    # truck-002 fixture has a temperature above the -12.0°C excursion threshold
    assert result["temperature_c"] > -12.0


def test_get_device_telemetry_truck003_offline(config):
    result = get_device_telemetry(config, device_id="truck-003")
    assert result["data_source"] == "mock"
    assert result["connectivity_status"] == "disconnected"


def test_get_device_telemetry_fallback_fixture(config):
    # warehouse-003 has no device-specific fixture — should fall back to default
    result = get_device_telemetry(config, device_id="warehouse-003")
    assert result["data_source"] == "mock"
    assert result["device_id"] == "warehouse-003"  # tool overwrites device_id
    assert "temperature_c" in result


# --- list_fleet_devices ---

def test_list_fleet_devices(config):
    result = list_fleet_devices(config)
    assert result["data_source"] == "mock"
    assert "devices" in result
    assert result["count"] == len(result["devices"])
    assert result["count"] == 5
    device_ids = {d["device_id"] for d in result["devices"]}
    assert "truck-001" in device_ids
    assert "truck-002" in device_ids
    assert "truck-003" in device_ids


# --- get_excursion_events ---

def test_get_excursion_events_no_excursion(config):
    result = get_excursion_events(config, device_id="truck-001")
    assert result["data_source"] == "mock"
    assert result["device_id"] == "truck-001"
    assert isinstance(result["events"], list)
    assert result["count"] == 0


def test_get_excursion_events_with_excursion(config):
    result = get_excursion_events(config, device_id="truck-002")
    assert result["data_source"] == "mock"
    assert result["device_id"] == "truck-002"
    assert result["count"] > 0
    first = result["events"][0]
    assert "started_at" in first
    assert "peak_temperature_c" in first


def test_get_excursion_events_hours_override(config):
    result = get_excursion_events(config, device_id="truck-001", hours=6)
    assert result["hours_queried"] == 6


# --- get_cloudwatch_alarm_state ---

def test_get_cloudwatch_alarm_state_alarm(config):
    result = get_cloudwatch_alarm_state(config, alarm_name="ColdChain-TemperatureHigh")
    assert result["data_source"] == "mock"
    assert result["state"] == "ALARM"
    assert result["alarm_name"] == "ColdChain-TemperatureHigh"


def test_get_cloudwatch_alarm_state_ok(config):
    result = get_cloudwatch_alarm_state(config, alarm_name="ColdChain-DLQDepth")
    assert result["data_source"] == "mock"
    assert result["state"] == "OK"


def test_get_cloudwatch_alarm_state_unknown_alarm(config):
    result = get_cloudwatch_alarm_state(config, alarm_name="ColdChain-Unknown")
    assert result["data_source"] == "mock"
    assert result["state"] == "OK"  # default fallback for unknown alarm names


# --- query_cloudwatch_logs ---

def test_query_cloudwatch_logs(config):
    result = query_cloudwatch_logs(
        config,
        log_group="/aws/iot/cold-chain/devices",
        query_string="fields @timestamp, @message | limit 10",
    )
    assert result["data_source"] == "mock"
    assert "results" in result
    assert isinstance(result["results"], list)
    assert result["status"] == "Complete"


# --- get_dlq_depth ---

def test_get_dlq_depth(config):
    result = get_dlq_depth(config, queue_name="iot-cold-chain-dlq")
    assert result["data_source"] == "mock"
    assert result["queue_name"] == "iot-cold-chain-dlq"
    assert isinstance(result["depth"], int)
    assert isinstance(result["in_flight"], int)


# --- get_device_shadow ---

def test_get_device_shadow_default(config):
    result = get_device_shadow(config, device_id="truck-001")
    assert result["data_source"] == "mock"
    assert "state" in result
    assert "reported" in result["state"]


def test_get_device_shadow_truck002_excursion(config):
    result = get_device_shadow(config, device_id="truck-002")
    assert result["data_source"] == "mock"
    reported_temp = result["state"]["reported"]["temperature_c"]
    assert reported_temp > -12.0  # shadow reflects the active excursion


def test_get_device_shadow_truck003_disconnected(config):
    result = get_device_shadow(config, device_id="truck-003")
    assert result["data_source"] == "mock"
    assert result["state"]["reported"]["connectivity"] == "disconnected"


# --- create_github_issue ---

def test_create_github_issue_write_denied(config_no_write):
    result = create_github_issue(config_no_write, title="Test", body="Test body")
    assert result["status"] == "error"
    assert result["error_type"] == "WritePermissionDenied"


def test_create_github_issue_mock(config):
    result = create_github_issue(
        config,
        title="Temperature excursion on truck-002",
        body="## Incident\n\nSustained excursion detected.",
    )
    assert result["data_source"] == "mock"
    assert result["status"] == "created"
    assert result["title"] == "Temperature excursion on truck-002"
    assert "issue_number" in result
    assert "issue_url" in result


# --- publish_sns_escalation ---

def test_publish_sns_escalation_write_denied(config_no_write):
    result = publish_sns_escalation(
        config_no_write, subject="Test", message="Test", severity="HIGH"
    )
    assert result["status"] == "error"
    assert result["error_type"] == "WritePermissionDenied"


def test_publish_sns_escalation_mock(config):
    result = publish_sns_escalation(
        config,
        subject="Temperature excursion alert",
        message="truck-002 has been above -12°C for 101 minutes.",
        severity="HIGH",
    )
    assert result["data_source"] == "mock"
    assert result["status"] == "published"
    assert result["subject"] == "Temperature excursion alert"
    assert result["severity"] == "HIGH"
    assert "message_id" in result
