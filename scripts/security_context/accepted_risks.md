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
