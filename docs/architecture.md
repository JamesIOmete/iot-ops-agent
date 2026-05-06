# Architecture

## Overview

`iot-ops-agent` is a production-disciplined autonomous AI agent for IoT cold chain fleet operations. It uses the Anthropic Claude API with native tool use to reason over live or mock AWS IoT data, execute runbooks, and produce structured outputs — without a human in the loop.

```
run.py                    # CLI: mode selection, config loading, mock/live flag
  └── AgentCore           # agent loop, tool dispatch, permission enforcement, logging
        ├── modes/
        │   ├── watchdog.py    # fleet health check prompt + result handling
        │   ├── incident.py    # runbook loader + incident prompt
        │   └── briefing.py    # on-demand status prompt
        ├── tools.py           # all 9 tool implementations (mock + live branches)
        └── escalation.py      # confidence check + keyword block logic
config/
  ├── config.yaml              # single source of truth for all thresholds and permissions
  └── runbooks/                # declarative YAML runbooks (no Python logic)
tests/
  ├── fixtures/                # realistic mock data for all 9 tools
  └── test_tools.py            # pytest coverage, zero AWS credentials required
logs/                          # JSONL reasoning logs, written incrementally
```

## Design Decisions

### Why tool use instead of prompt chaining?
The Anthropic tool use API lets the model decide which tools to call, in what order, based on what it finds. This produces adaptive, evidence-driven investigation — not a fixed script. The runbook provides structure; the model provides judgment.

### Why a single AgentCore instead of per-mode classes?
Permission enforcement, token tracking, and log writing are invariants across all modes. Centralising them in `AgentCore` means a permission violation in watchdog mode is caught by exactly the same code path as one in incident mode. Duplication would create drift.

### Why mock mode as the default?
The agent must be demonstrable without AWS credentials. Mock mode is not a test shim — it is a first-class operating mode that uses realistic fixture data and produces real reasoning logs. The `data_source` field in every tool result makes mock vs live transparent in the log.

### Why escalation.py as a separate module?
Escalation is a first-class outcome, not an error handler. By keeping all escalation logic in one file (`check_escalation`, `build_escalation_payload`), the decision rules are auditable in one place. Mode files and tool functions never make escalation decisions — they gather evidence and let the agent reason.

### Why YAML runbooks?
Runbooks encode operational knowledge, not Python logic. YAML runbooks are readable by SREs without a Python background, version-controlled, and diffable. They define steps, tool hints, and hypotheses. The agent reads them as prompts — it interprets them, it does not execute them line by line.

### Why incremental log writes?
If the agent crashes mid-run, the partial JSONL log is still valid. Every event is flushed immediately after writing. This matters in production: an agent that dies on step 4 of 7 should leave an auditable trail of steps 1–4, not an empty file.

## Agent Loop

```
run_start event
  ↓
[LLM call] → reasoning_step events for text blocks
  ↓
tool_use blocks → _dispatch_tool() for each
  ├── permission check → tool_permission_violation event + ToolPermissionError if denied
  ├── tool_call event (before execution)
  └── tool_result or tool_failure event (after execution)
  ↓
tool results added to messages → next LLM call
  ↓
(repeat until stop_reason == end_turn or max_tool_calls reached)
  ↓
run_end event (with total token counts)
```

## Permission Model

Permissions are read from `config.yaml` at startup and enforced at two layers:
1. `AgentCore._dispatch_tool()` checks mode allowlist and `allow_write_actions` flag.
2. Write tools (`create_github_issue`, `publish_sns_escalation`) independently check `config.runtime.allow_write_actions` before executing. Two checks, intentionally redundant.

A violation at layer 1 raises `ToolPermissionError`, which is logged as `tool_permission_violation` and returned to the model as an error tool result. The model can adjust its approach; if it cannot, it will ultimately end its turn.

## Token Cost Estimates

| Mode | Typical tool calls | Estimated input tokens | Estimated output tokens |
|------|-------------------|----------------------|------------------------|
| Briefing | 8–12 | 8,000–15,000 | 500–1,000 |
| Watchdog | 15–25 | 15,000–30,000 | 800–1,500 |
| Incident | 20–40 | 20,000–40,000 | 1,000–2,500 |

Costs are dominated by tool result tokens returned to the model. Each tool result is included in full in subsequent LLM call contexts (Anthropic's context window, not a vector store). Token counts are accumulated per run and written to the `run_end` log event.

## Known Optimization Opportunities

### Incident Mode Token Cost

Incident mode input token cost is significantly higher than Watchdog
or Briefing (~40k input tokens vs ~6-8k). The primary driver is full
telemetry history pulls across multiple devices during runbook steps
1–2, combined with growing reasoning context across a 5-step
investigation.

Production optimization: scope telemetry queries to the alarm window
only (e.g. 2h lookback) rather than the default 24h, unless
cross-day correlation is explicitly required by the runbook step.
This change alone would reduce incident mode input tokens by an
estimated 50–60%.

A secondary optimization is to gate CloudWatch Logs queries behind
the infrastructure check step result — if DLQ is clean and no
ingestor errors are present, skip the full log query. The runbook
condition syntax supports this (`condition.if`) but the current
implementation pulls logs regardless.

These are deliberate portfolio tradeoffs — the current implementation
prioritizes completeness of investigation over token efficiency, which
is the correct default for a first deployment. Optimization should be
data-driven once real incident patterns are established.


## Mock Mode

In mock mode (`--mock` flag, default on), every tool returns fixture data from `tests/fixtures/`. No AWS calls are made, no credentials are required. The fixture data tells a coherent story: truck-002 has an active temperature excursion, truck-003 is silent, all other devices are normal. This makes mock mode useful for demos, CI, and development.

The `data_source` field in every tool result is `"mock"` in mock mode and the actual AWS service name (`"dynamodb"`, `"cloudwatch"`, `"sqs"`, `"iot_shadow"`, `"sns"`, `"github"`) in live mode.
