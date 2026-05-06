import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3


def load_fixture(tool_name: str, **kwargs) -> dict:
    fixture_dir = Path(__file__).parent.parent / "tests" / "fixtures"

    if "device_id" in kwargs:
        device_path = fixture_dir / f"{tool_name}_{kwargs['device_id']}.json"
        if device_path.exists():
            with open(device_path) as f:
                return json.load(f)

    base_path = fixture_dir / f"{tool_name}.json"
    if base_path.exists():
        with open(base_path) as f:
            return json.load(f)

    raise FileNotFoundError(f"No fixture found for tool '{tool_name}' with kwargs {kwargs}")


def get_device_telemetry(config: dict, device_id: str) -> dict:
    if config["runtime"]["mock_mode"]:
        data = load_fixture("get_device_telemetry", device_id=device_id)
        data["device_id"] = device_id
        return data
    try:
        dynamodb = boto3.resource("dynamodb", region_name=config["aws"]["region"])
        table = dynamodb.Table(config["aws"]["dynamodb"]["telemetry_table"])
        response = table.get_item(Key={"device_id": device_id})
        item = response.get("Item", {})
        item["data_source"] = "dynamodb"
        return item
    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "data_source": "dynamodb",
        }


def list_fleet_devices(config: dict) -> dict:
    if config["runtime"]["mock_mode"]:
        return load_fixture("list_fleet_devices")
    try:
        dynamodb = boto3.resource("dynamodb", region_name=config["aws"]["region"])
        table = dynamodb.Table(config["aws"]["dynamodb"]["devices_table"])
        response = table.scan()
        devices = response.get("Items", [])
        return {"devices": devices, "count": len(devices), "data_source": "dynamodb"}
    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "data_source": "dynamodb",
        }


def get_excursion_events(config: dict, device_id: str, hours: int = 24) -> dict:
    if config["runtime"]["mock_mode"]:
        data = load_fixture("get_excursion_events", device_id=device_id)
        data["device_id"] = device_id
        data["hours_queried"] = hours
        return data
    try:
        from boto3.dynamodb.conditions import Key

        dynamodb = boto3.resource("dynamodb", region_name=config["aws"]["region"])
        table = dynamodb.Table(config["aws"]["dynamodb"]["excursions_table"])
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        response = table.query(
            KeyConditionExpression=Key("device_id").eq(device_id)
            & Key("started_at").gte(cutoff)
        )
        events = response.get("Items", [])
        return {
            "device_id": device_id,
            "hours_queried": hours,
            "events": events,
            "count": len(events),
            "data_source": "dynamodb",
        }
    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "data_source": "dynamodb",
        }


def get_cloudwatch_alarm_state(config: dict, alarm_name: str) -> dict:
    if config["runtime"]["mock_mode"]:
        fixture = load_fixture("get_cloudwatch_alarm_state")
        for alarm in fixture.get("alarms", []):
            if alarm["alarm_name"] == alarm_name:
                return {**alarm, "data_source": "mock"}
        return {
            "alarm_name": alarm_name,
            "state": "OK",
            "state_reason": "No mock data for this alarm",
            "data_source": "mock",
        }
    try:
        cw = boto3.client("cloudwatch", region_name=config["aws"]["region"])
        response = cw.describe_alarms(AlarmNames=[alarm_name])
        alarms = response.get("MetricAlarms", [])
        if not alarms:
            return {"alarm_name": alarm_name, "state": "NOT_FOUND", "data_source": "cloudwatch"}
        alarm = alarms[0]
        updated = alarm.get("StateUpdatedTimestamp")
        return {
            "alarm_name": alarm_name,
            "state": alarm["StateValue"],
            "state_reason": alarm.get("StateReason", ""),
            "state_updated": updated.isoformat() if updated else "",
            "data_source": "cloudwatch",
        }
    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "data_source": "cloudwatch",
        }


def query_cloudwatch_logs(
    config: dict, log_group: str, query_string: str, hours: int = 1
) -> dict:
    if config["runtime"]["mock_mode"]:
        return load_fixture("query_cloudwatch_logs")
    import time

    try:
        logs = boto3.client("logs", region_name=config["aws"]["region"])
        end_time = int(time.time())
        start_time = end_time - (hours * 3600)
        response = logs.start_query(
            logGroupName=log_group,
            startTime=start_time,
            endTime=end_time,
            queryString=query_string,
            limit=100,
        )
        query_id = response["queryId"]
        for _ in range(15):
            time.sleep(2)
            result = logs.get_query_results(queryId=query_id)
            if result["status"] in ("Complete", "Failed", "Cancelled"):
                break
        rows = [
            {f["field"]: f["value"] for f in row}
            for row in result.get("results", [])
        ]
        return {
            "status": result["status"],
            "results": rows,
            "statistics": result.get("statistics", {}),
            "data_source": "cloudwatch_logs",
        }
    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "data_source": "cloudwatch_logs",
        }


def get_dlq_depth(config: dict, queue_name: str) -> dict:
    if config["runtime"]["mock_mode"]:
        data = load_fixture("get_dlq_depth")
        data["queue_name"] = queue_name
        return data
    try:
        sqs = boto3.client("sqs", region_name=config["aws"]["region"])
        url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
        attrs = sqs.get_queue_attributes(
            QueueUrl=url,
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
            ],
        )["Attributes"]
        return {
            "queue_name": queue_name,
            "depth": int(attrs.get("ApproximateNumberOfMessages", 0)),
            "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
            "data_source": "sqs",
        }
    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "data_source": "sqs",
        }


def get_device_shadow(config: dict, device_id: str) -> dict:
    if config["runtime"]["mock_mode"]:
        return load_fixture("get_device_shadow", device_id=device_id)
    try:
        iot_data = boto3.client(
            "iot-data",
            endpoint_url=f"https://{config['aws']['iot']['endpoint']}",
            region_name=config["aws"]["region"],
        )
        response = iot_data.get_thing_shadow(thingName=device_id)
        shadow = json.loads(response["payload"].read())
        shadow["data_source"] = "iot_shadow"
        return shadow
    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "data_source": "iot_shadow",
        }


def create_github_issue(
    config: dict, title: str, body: str, labels: list = None
) -> dict:
    if not config["runtime"].get("allow_write_actions", False):
        return {
            "status": "error",
            "error_type": "WritePermissionDenied",
            "error_message": "Write actions not permitted in current configuration",
            "data_source": "mock",
        }
    if config["runtime"]["mock_mode"]:
        data = load_fixture("create_github_issue")
        data["title"] = title
        return data
    try:
        from github import Github

        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise ValueError("GITHUB_TOKEN environment variable not set")
        gh = Github(token)
        repo = gh.get_repo(config["github"]["repo"])
        label_names = labels or config["github"]["default_labels"]
        issue = repo.create_issue(title=title, body=body, labels=label_names)
        return {
            "status": "created",
            "issue_number": issue.number,
            "issue_url": issue.html_url,
            "title": title,
            "data_source": "github",
        }
    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "data_source": "github",
        }


def publish_sns_escalation(
    config: dict, subject: str, message: str, severity: str
) -> dict:
    if not config["runtime"].get("allow_write_actions", False):
        return {
            "status": "error",
            "error_type": "WritePermissionDenied",
            "error_message": "Write actions not permitted in current configuration",
            "data_source": "mock",
        }
    if config["runtime"]["mock_mode"]:
        data = load_fixture("publish_sns_escalation")
        data["subject"] = subject
        data["severity"] = severity
        return data
    try:
        sns = boto3.client("sns", region_name=config["aws"]["region"])
        topic_arn = config["aws"]["sns"]["escalation_topic_arn"]
        response = sns.publish(
            TopicArn=topic_arn,
            Subject=f"[{severity}] IoT Alert: {subject}",
            Message=f"[{severity}] {message}",
            MessageAttributes={"severity": {"DataType": "String", "StringValue": severity}},
        )
        return {
            "status": "published",
            "message_id": response["MessageId"],
            "subject": subject,
            "severity": severity,
            "data_source": "sns",
        }
    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "data_source": "sns",
        }


TOOL_SCHEMAS = [
    {
        "name": "get_device_telemetry",
        "description": (
            "Retrieve current telemetry for a specific IoT device from DynamoDB. "
            "Returns temperature, humidity, battery, GPS, connectivity status, and last heartbeat."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "Device ID (e.g. 'truck-001', 'warehouse-002')",
                }
            },
            "required": ["device_id"],
        },
    },
    {
        "name": "list_fleet_devices",
        "description": (
            "List all devices in the IoT fleet with their current status, type, and last heartbeat."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_excursion_events",
        "description": (
            "Retrieve temperature excursion events for a device over a time window. "
            "An excursion is when temperature exceeded a configured threshold."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Device ID to query"},
                "hours": {
                    "type": "integer",
                    "description": "Hours to look back (default 24)",
                },
            },
            "required": ["device_id"],
        },
    },
    {
        "name": "get_cloudwatch_alarm_state",
        "description": (
            "Get the current state (ALARM, OK, INSUFFICIENT_DATA) of a CloudWatch alarm."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "alarm_name": {"type": "string", "description": "CloudWatch alarm name"}
            },
            "required": ["alarm_name"],
        },
    },
    {
        "name": "query_cloudwatch_logs",
        "description": (
            "Run a CloudWatch Logs Insights query. Useful for diagnosing connectivity issues "
            "or sensor errors. Not available in briefing mode."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "log_group": {
                    "type": "string",
                    "description": "CloudWatch log group name",
                },
                "query_string": {
                    "type": "string",
                    "description": "CloudWatch Logs Insights query string",
                },
                "hours": {
                    "type": "integer",
                    "description": "Hours to look back (default 1)",
                },
            },
            "required": ["log_group", "query_string"],
        },
    },
    {
        "name": "get_dlq_depth",
        "description": (
            "Get the approximate message count in an SQS Dead Letter Queue. "
            "High depth indicates devices failing to deliver telemetry."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "queue_name": {"type": "string", "description": "SQS queue name"}
            },
            "required": ["queue_name"],
        },
    },
    {
        "name": "get_device_shadow",
        "description": (
            "Get the AWS IoT Device Shadow: desired vs reported state, connectivity, "
            "and last update timestamp. Incident mode only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Device ID"}
            },
            "required": ["device_id"],
        },
    },
    {
        "name": "create_github_issue",
        "description": (
            "Create a GitHub issue to track an IoT incident. "
            "Write action — requires allow_write_actions. Incident mode only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Issue title"},
                "body": {
                    "type": "string",
                    "description": "Issue body with incident details in markdown",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to apply (optional)",
                },
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "publish_sns_escalation",
        "description": (
            "Publish an escalation notification to SNS. "
            "Write action — requires allow_write_actions. Incident mode only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Notification subject"},
                "message": {
                    "type": "string",
                    "description": "Detailed escalation message",
                },
                "severity": {
                    "type": "string",
                    "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
                    "description": "Escalation severity level",
                },
            },
            "required": ["subject", "message", "severity"],
        },
    },
]
