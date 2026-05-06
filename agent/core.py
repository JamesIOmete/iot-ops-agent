import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from agent.tools import (
    TOOL_SCHEMAS,
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

TOOL_REGISTRY = {
    "get_device_telemetry": get_device_telemetry,
    "list_fleet_devices": list_fleet_devices,
    "get_excursion_events": get_excursion_events,
    "get_cloudwatch_alarm_state": get_cloudwatch_alarm_state,
    "query_cloudwatch_logs": query_cloudwatch_logs,
    "get_dlq_depth": get_dlq_depth,
    "get_device_shadow": get_device_shadow,
    "create_github_issue": create_github_issue,
    "publish_sns_escalation": publish_sns_escalation,
}

WRITE_TOOLS = {"create_github_issue", "publish_sns_escalation"}


class ToolPermissionError(Exception):
    pass


class AgentCore:
    def __init__(self, config: dict, mode: str):
        self.config = config
        self.mode = mode
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

        allowed = set(config["tool_permissions"][mode]["allowed_tools"])
        self.active_tools = [t for t in TOOL_SCHEMAS if t["name"] in allowed]

        self._log_path: Path | None = None
        self._log_file = None
        self._run_id: str | None = None
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._tool_call_count = 0

    def run(self, user_message: str, system_prompt: str) -> dict:
        self._run_id = str(uuid.uuid4())[:8]
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._tool_call_count = 0

        log_dir = Path(self.config["runtime"]["log_dir"])
        log_dir.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._log_path = log_dir / f"{self.mode}_{ts}_{self._run_id}.jsonl"

        try:
            self._log_file = open(self._log_path, "w")
            self._write_event(
                {
                    "type": "run_start",
                    "run_id": self._run_id,
                    "mode": self.mode,
                    "mock_mode": self.config["runtime"]["mock_mode"],
                    "model": self.config["model"]["id"],
                    "active_tools": [t["name"] for t in self.active_tools],
                }
            )

            messages = [{"role": "user", "content": user_message}]
            max_tool_calls = self.config["modes"][self.mode]["max_tool_calls"]
            final_text = ""

            while True:
                self._write_event(
                    {
                        "type": "llm_request",
                        "message_count": len(messages),
                        "tool_calls_so_far": self._tool_call_count,
                    }
                )

                response = self.client.messages.create(
                    model=self.config["model"]["id"],
                    max_tokens=self.config["model"]["max_tokens"],
                    system=system_prompt,
                    tools=self.active_tools,
                    messages=messages,
                )

                self._write_event(
                    {
                        "type": "llm_response",
                        "stop_reason": response.stop_reason,
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                    }
                )
                self._total_input_tokens += response.usage.input_tokens
                self._total_output_tokens += response.usage.output_tokens

                tool_uses = []
                for block in response.content:
                    if block.type == "text":
                        self._write_event({"type": "reasoning_step", "text": block.text})
                        final_text = block.text
                    elif block.type == "tool_use":
                        tool_uses.append(block)

                messages.append({"role": "assistant", "content": response.content})

                if response.stop_reason == "end_turn" or not tool_uses:
                    break

                if self._tool_call_count >= max_tool_calls:
                    self._write_event(
                        {
                            "type": "escalation",
                            "reason": f"max_tool_calls ({max_tool_calls}) reached without conclusion",
                        }
                    )
                    break

                tool_results = []
                for tool_use in tool_uses:
                    try:
                        result = self._dispatch_tool(tool_use.name, tool_use.input)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": json.dumps(result),
                            }
                        )
                    except ToolPermissionError as exc:
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "is_error": True,
                                "content": str(exc),
                            }
                        )

                messages.append({"role": "user", "content": tool_results})

            self._write_event(
                {
                    "type": "run_end",
                    "status": "complete",
                    "total_input_tokens": self._total_input_tokens,
                    "total_output_tokens": self._total_output_tokens,
                    "tool_calls_made": self._tool_call_count,
                    "log_path": str(self._log_path),
                }
            )

            return {
                "status": "complete",
                "summary": final_text,
                "log_path": str(self._log_path),
                "input_tokens": self._total_input_tokens,
                "output_tokens": self._total_output_tokens,
            }

        except Exception:
            self._write_event(
                {
                    "type": "run_end",
                    "status": "error",
                    "total_input_tokens": self._total_input_tokens,
                    "total_output_tokens": self._total_output_tokens,
                }
            )
            raise

        finally:
            if self._log_file:
                self._log_file.close()

    def _dispatch_tool(self, tool_name: str, tool_input: dict) -> dict:
        allowed_tools = self.config["tool_permissions"][self.mode]["allowed_tools"]

        if tool_name not in allowed_tools:
            self._write_event(
                {
                    "type": "tool_permission_violation",
                    "tool_name": tool_name,
                    "mode": self.mode,
                    "reason": "tool not in allowed_tools for mode",
                }
            )
            raise ToolPermissionError(
                f"Tool '{tool_name}' is not permitted in {self.mode} mode"
            )

        allow_write = self.config["runtime"].get("allow_write_actions", False)
        if tool_name in WRITE_TOOLS and not allow_write:
            self._write_event(
                {
                    "type": "tool_permission_violation",
                    "tool_name": tool_name,
                    "mode": self.mode,
                    "reason": "allow_write_actions is false",
                }
            )
            raise ToolPermissionError(
                f"Write tool '{tool_name}' requires --allow-write flag"
            )

        self._write_event(
            {
                "type": "tool_call",
                "tool_name": tool_name,
                "tool_input": tool_input,
                "call_number": self._tool_call_count + 1,
            }
        )
        self._tool_call_count += 1

        try:
            tool_fn = TOOL_REGISTRY[tool_name]
            result = tool_fn(self.config, **tool_input)
            self._write_event(
                {
                    "type": "tool_result",
                    "tool_name": tool_name,
                    "data_source": result.get("data_source", "unknown"),
                    "result_status": result.get("status", "ok"),
                }
            )
            return result
        except Exception as exc:
            error = {
                "status": "error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "data_source": "unknown",
            }
            self._write_event({"type": "tool_failure", "tool_name": tool_name, "error": error})
            return error

    def _write_event(self, event: dict) -> None:
        event["timestamp"] = datetime.now(timezone.utc).isoformat()
        if self._run_id:
            event["run_id"] = self._run_id
        self._log_file.write(json.dumps(event) + "\n")
        self._log_file.flush()
