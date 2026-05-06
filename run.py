#!/usr/bin/env python3
"""CLI entrypoint for iot-ops-agent."""
import argparse
import sys
from pathlib import Path

import yaml

from agent.core import AgentCore
from agent.modes import briefing, incident, watchdog


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_config(config_override_path: str | None) -> dict:
    config_path = Path(__file__).parent / "config" / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    if config_override_path:
        with open(config_override_path) as f:
            override = yaml.safe_load(f)
        _deep_merge(config, override)
    return config


def main() -> int:
    parser = argparse.ArgumentParser(
        description="IoT Ops Agent — autonomous fleet operations for cold chain IoT."
    )
    parser.add_argument(
        "--mode",
        choices=["watchdog", "incident", "briefing"],
        required=True,
        help="Agent operating mode",
    )
    parser.add_argument(
        "--no-mock",
        dest="mock",
        action="store_false",
        default=True,
        help="Use live AWS (default: mock mode)",
    )
    parser.add_argument(
        "--allow-write",
        action="store_true",
        default=False,
        help="Enable write actions (create_github_issue, publish_sns_escalation)",
    )
    parser.add_argument(
        "--config-override",
        type=str,
        default=None,
        help="Path to a YAML config override file (deep-merged over config.yaml)",
    )
    parser.add_argument(
        "--runbook",
        type=str,
        default="temperature_excursion",
        help="Runbook ID for incident mode (default: temperature_excursion)",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Device ID to target for incident mode",
    )
    args = parser.parse_args()

    config = _load_config(args.config_override)

    # Apply runtime overrides
    config["runtime"]["mock_mode"] = args.mock
    config["runtime"]["mode"] = args.mode

    # Honour --allow-write for the active mode
    if args.allow_write:
        config["tool_permissions"][args.mode]["allow_write_actions"] = True
    config["runtime"]["allow_write_actions"] = config["tool_permissions"][args.mode][
        "allow_write_actions"
    ]

    core = AgentCore(config, mode=args.mode)

    if args.mode == "watchdog":
        result = watchdog.run(config, core)
    elif args.mode == "incident":
        result = incident.run(config, core, runbook_id=args.runbook, device_id=args.device)
    else:
        result = briefing.run(config, core)

    print(result.get("summary", ""))
    print(
        f"\n[run complete — log: {result.get('log_path', 'N/A')} | "
        f"tokens in/out: {result.get('input_tokens', 0)}/{result.get('output_tokens', 0)}]"
    )

    return 0 if result.get("status") != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
