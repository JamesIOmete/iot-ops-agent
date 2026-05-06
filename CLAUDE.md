# CLAUDE.md
# Behavioral guidelines for Claude Code working in iot-ops-agent.
# Section 1: General LLM coding discipline (Karpathy-derived).
# Section 2: iot-ops-agent-specific rules.
# Both sections are active. Read both before touching anything.

---

## Section 1 — General Coding Discipline

Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** These guidelines bias toward caution over speed.
For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?"
If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

[Step] → verify: [check]
[Step] → verify: [check]
[Step] → verify: [check]


Strong success criteria let you loop independently.
Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs,
fewer rewrites due to overcomplication, and clarifying questions come
before implementation rather than after mistakes.

---

## Section 2 — iot-ops-agent Project Rules

These rules encode architectural decisions made during planning.
They are not suggestions. Violating them produces a repo that
contradicts its own design documentation.

### Repo Role and Audience

This is a portfolio project targeting IoT Solutions Architect and
Cloud Solutions Architect hiring managers. Every design decision
must be visible and defensible — not just working. Code that works
but doesn't show its reasoning is a failure for this repo's purpose.

### File Ownership — Touch Only What the Task Requires

| File | Owner | Rule |
|------|-------|------|
| `agent/core.py` | Agent loop and tool dispatch | Only touch for loop logic, permission enforcement, token tracking |
| `agent/tools.py` | Tool registry and implementations | One function per tool. Mock/live branch in every tool. |
| `agent/modes/watchdog.py` | Watchdog mode logic | No tool calls here — tools are dispatched via core.py |
| `agent/modes/incident.py` | Incident mode and runbook execution | Reads runbooks from config/runbooks/ — no hardcoded steps |
| `agent/modes/briefing.py` | Briefing mode logic | No tool calls here — tools are dispatched via core.py |
| `agent/escalation.py` | Escalation logic and thresholds | All escalation decisions live here. Never scattered in mode files. |
| `config/config.yaml` | Runtime configuration | Source of truth for all thresholds and permissions. Never hardcode values that appear here. |
| `config/runbooks/` | YAML runbook definitions | Declarative only — no Python logic in runbook files |
| `tests/fixtures/` | Mock data for all tools | Every tool must have a corresponding fixture file |
| `docs/tool-registry.md` | Tool definitions and permissions | Update whenever tool_permissions in config.yaml changes |

### Tool Implementation Rules

Every function in `agent/tools.py` must:

1. **Have a mock branch.** Every tool checks `config.runtime.mock_mode`
   and returns fixture data if true. No AWS call is made in mock mode.
```python
   if config["runtime"]["mock_mode"]:
       return load_fixture("get_device_telemetry", device_id=device_id)
```

2. **Include `data_source` in its return value.** Always `"mock"` or
   the actual AWS service name (`"dynamodb"`, `"cloudwatch"`,
   `"cloudwatch_logs"`, `"sqs"`, `"sns"`, `"iot_shadow"`).
   Never hardcode `"dynamodb"` when running in mock mode.

3. **Have a corresponding fixture file.** A tool without a fixture
   in `tests/fixtures/` is incomplete. CI should enforce this.
   Fixture filename convention: `{tool_name}.json`
   For device-scoped tools: `{tool_name}_{device_id}.json`

4. **Handle failures explicitly.** Every AWS call is wrapped in
   try/except. Failures return a structured error dict — they do
   not raise exceptions that crash the agent loop.
```python
   return {
       "status": "error",
       "error_type": "timeout",
       "error_message": str(e),
       "data_source": "dynamodb"
   }
```

5. **Never exceed their permission tier.** Read tools must have no
   side effects. Write tools check `allow_write_actions` before
   executing. This check is also enforced at dispatch in core.py —
   defence in depth, not redundancy.

### Permission Enforcement Rules

- Tool permissions are read from `config.yaml` at startup, not
  hardcoded in Python.
- `core.py` checks mode permission before dispatching every tool call.
- A tool call attempted outside permitted modes raises
  `ToolPermissionError` and is logged as `tool_permission_violation`.
  It is never silently skipped.
- Write tools (`create_github_issue`, `publish_sns_escalation`)
  additionally check `allow_write_actions` flag at the tool level.
  Two checks, not one.

### Reasoning Log Rules

- Every tool call produces a `tool_call` event before execution
  and a `tool_result` or `tool_failure` event after.
- Every LLM text block between tool calls produces a
  `reasoning_step` event.
- Token counts from every API response are recorded in the
  `llm_response` event and accumulated in `run_end`.
- Log files are written incrementally — not assembled at the end.
  If the agent crashes mid-run, the partial log is valid and readable.
- Log files go to `logs/`. The `logs/` directory is gitignored
  except for `logs/examples/` which contains curated example runs.

### Configuration Rules

- All thresholds live in `config/config.yaml`. No magic numbers
  in agent code. If you find yourself writing `if temp > 8.0`,
  that value comes from config.
- Config is loaded once at startup and passed through as a dict.
  No module-level config reads — makes testing clean.
- `mock_mode: true` is the default in `config.yaml`.
  Live mode requires explicit override: `--no-mock` at CLI or
  `runtime.mock_mode: false` in a config override file.

### Escalation Rules

- All escalation logic lives in `agent/escalation.py`.
- Escalation is never decided inside mode files or tool functions.
- Escalation is a first-class outcome, not an error handler.
  It gets an `escalation` event in the reasoning log and a
  clean exit from the agent loop — not a stack trace.
- The `never_auto_remediate` keyword list in config.yaml is
  checked against recommended action text before any write action.
  If there's a match, the action is blocked and escalation fires.

### Testing Rules

- Every tool function has at least one pytest test in
  `tests/test_tools.py` that runs in mock mode.
- Mock mode tests require no AWS credentials and no network access.
- Test fixture data must be realistic — not `"temp": 999` or
  `"device_id": "test"`. Use fixture data that looks like
  production cold chain data.
- The command `pytest tests/ -v` must pass with zero AWS
  credentials present. This is the CI baseline.
- Integration tests (live AWS) go in `tests/test_integration/`
  and are skipped by default: `@pytest.mark.integration`

### What Claude Code Must Never Do in This Repo

- Never hardcode an AWS resource name, ARN, or URL. They live
  in `config/config.yaml`.
- Never add a tool to `tools.py` without a fixture in
  `tests/fixtures/` and a test in `tests/test_tools.py`.
- Never put escalation logic in a mode file.
- Never put threshold values in agent code.
- Never write a tool that makes an AWS call without a mock branch.
- Never modify `docs/tool-registry.md` and `config/config.yaml`
  tool_permissions independently — they must stay in sync.
- Never write a mode file that calls a tool directly — all tool
  dispatch goes through `core.py`.
- Never add `print()` statements for debugging — use the
  structured logger.
- Never commit a log file outside `logs/examples/`.

### Commit Message Convention
<type>(<scope>): <summary>
Types: feat | fix | test | docs | config | refactor
Scope: core | tools | watchdog | incident | briefing | escalation | config | docs
Examples:
feat(tools): add get_device_shadow with mock and live branches
test(tools): add fixture and pytest coverage for get_dlq_depth
config(runbooks): add device_silence runbook
docs(tool-registry): sync permissions after adding get_device_shadow

### Cost Awareness

Token usage is tracked per run. When implementing features that
add LLM calls or expand context, note the expected token impact
in a code comment. The README documents expected cost per mode —
if your changes materially affect token usage, update it.
