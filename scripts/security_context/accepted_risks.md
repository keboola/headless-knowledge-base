# Accepted Security Risks

## ADR-001: Default ADMIN_PASSWORD

**Status:** Accepted
**Date:** 2026-02-19

### Context
`config.py` has `ADMIN_PASSWORD: str = "changeme"` as the default value.

### Decision
ACCEPTED - The config.py model_validator checks for this default and logs a security warning at startup when DEBUG=False. This is standard practice for local development defaults.

### Consequence
The security reviewer should NOT flag the `ADMIN_PASSWORD: str = "changeme"` line in config.py as a hardcoded credential. It IS a known default with runtime protection.

## ADR-002: Empty String Defaults for Optional Credentials

**Status:** Accepted
**Date:** 2026-02-19

### Context
Config settings like `ANTHROPIC_API_KEY: str = ""`, `SLACK_BOT_TOKEN: str = ""` use empty string defaults.

### Decision
ACCEPTED - These are pydantic-settings fields populated from environment variables. Empty defaults allow the app to start in limited mode (e.g., without Slack) for testing. Required credentials are validated at the point of use.

## ADR-003: Documentation Security Anti-Patterns

**Status:** Accepted
**Date:** 2026-02-19

### Context
repository_context.md and accepted_risks.md contain example credential patterns for the security reviewer to learn from.

### Decision
ACCEPTED - These are documentation examples, not real credentials.

## ADR-004: AI Reviewer Scripts — External API Communication

**Status:** Accepted
**Date:** 2026-02-19

### Context
`scripts/ai_reviewer.py` and `scripts/security_reviewer.py` send PR content (diffs, file contents) to external LLM APIs (Google Gemini and Anthropic Claude) for analysis. This is their core purpose.

### Decision
ACCEPTED - Sending code to external LLM APIs is the fundamental design of AI code review. Both APIs have enterprise data handling policies. The `html.escape()` sanitization and explicit prompt injection defenses are adequate. Pre-scan findings are excluded from reviewer scripts themselves to prevent self-referential false positives.

### Consequence
The security reviewer should NOT flag:
- `scripts/ai_reviewer.py` or `scripts/security_reviewer.py` for "sending code to external APIs"
- `scripts/security_context/sensitive_patterns.py` for "containing credential patterns" (they are regex definitions, not real credentials)
- Reviewer scripts for "hardcoded credential patterns" (the patterns are regex strings for detection, not actual credentials)

## ADR-005: AI Reviewer Scripts — Credential Validation

**Status:** Accepted
**Date:** 2026-02-19

### Context
Both `ai_reviewer.py` (line 266-269) and `security_reviewer.py` (line 356-359) validate their respective API keys at script entry point with `sys.exit(1)` on missing keys. The CI workflow also validates `GEMINI_API_KEY` before running the script.

### Decision
ACCEPTED - API key validation exists at multiple levels (CI + script). No additional validation needed.
