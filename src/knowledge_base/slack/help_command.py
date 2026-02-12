"""Fancy /help command for the Knowledge Base bot."""

import logging
from typing import Any

from slack_sdk import WebClient

logger = logging.getLogger(__name__)

def _get_help_sections() -> dict:
    """Build help content with correct command prefix for the environment."""
    from knowledge_base.config import settings
    p = settings.SLACK_COMMAND_PREFIX

    return {
        "ask": {
            "title": "Asking Questions",
            "icon": "mag",
            "commands": [
                {
                    "usage": "@KnowledgeBot <question>",
                    "description": "Ask any question - I'll search the knowledge base and provide an answer with sources.",
                    "examples": [
                        "How do I request vacation time?",
                        "What's the deployment process?",
                        "Who manages the Snowflake account?",
                    ],
                },
                {
                    "usage": "DM the bot",
                    "description": "Send me a direct message for private conversations.",
                    "examples": ["Just open a DM and ask away!"],
                },
            ],
        },
        "create": {
            "title": "Creating Knowledge",
            "icon": "bulb",
            "commands": [
                {
                    "usage": f"/{p}create-knowledge <fact>",
                    "description": "Add a quick fact to the knowledge base. Great for tribal knowledge!",
                    "examples": [
                        f"/{p}create-knowledge The admin of Snowflake is @sarah",
                        f"/{p}create-knowledge To request AWS access, ask in #platform-access",
                        f"/{p}create-knowledge Weekly standup is at 9am in #engineering-standup",
                    ],
                },
                {
                    "usage": f"/{p}create-doc",
                    "description": "Create a formal document with AI assistance. Opens a form to fill out.",
                    "examples": ["Use for policies, procedures, guidelines"],
                },
                {
                    "usage": "Save as Doc (message shortcut)",
                    "description": "Convert a Slack thread into documentation. Right-click a message → More actions → Save as Doc",
                    "examples": ["Great for preserving troubleshooting sessions or decisions"],
                },
            ],
        },
        "ingest": {
            "title": "Importing External Docs",
            "icon": "inbox_tray",
            "commands": [
                {
                    "usage": f"/{p}ingest-doc <url>",
                    "description": "Import external documents into the knowledge base.",
                    "examples": [
                        f"/{p}ingest-doc https://docs.company.com/guide.pdf",
                        f"/{p}ingest-doc https://docs.google.com/document/d/xxx",
                        f"/{p}ingest-doc https://wiki.company.com/runbooks",
                    ],
                    "supported": ["Web pages", "PDFs", "Google Docs (public)", "Notion (public)"],
                },
            ],
        },
        "feedback": {
            "title": "Improving Answers",
            "icon": "chart_with_upwards_trend",
            "commands": [
                {
                    "usage": "Feedback buttons",
                    "description": "After each answer, use the buttons to rate it:",
                    "options": [
                        ("thumbsup", "Helpful - The answer was accurate and useful"),
                        ("hourglass", "Outdated - Information is no longer current"),
                        ("x", "Incorrect - The answer contains errors"),
                        ("question", "Confusing - The answer is unclear"),
                    ],
                },
                {
                    "usage": "Emoji reactions",
                    "description": "React to bot messages with thumbsup/thumbsdown for quick feedback.",
                    "examples": [],
                },
                {
                    "usage": "Say thanks!",
                    "description": "When an answer helps, saying 'Thanks!' in the thread lets me know it was useful.",
                    "examples": [],
                },
            ],
        },
        "tips": {
            "title": "Pro Tips",
            "icon": "star2",
            "tips": [
                "Be specific in your questions for better answers",
                "Ask follow-up questions in the same thread for context",
                f"Use /{p}create-knowledge for those 'I wish someone told me this' moments",
                "Feedback helps improve rankings - the more you rate, the smarter I get!",
                "Negative feedback? I'll offer to bring in an admin to help improve the content",
            ],
        },
    }


# Keep module-level reference for backward compatibility
HELP_SECTIONS = _get_help_sections()


def build_help_blocks(section: str | None = None) -> list[dict]:
    """Build Slack Block Kit blocks for help content.

    Args:
        section: Optional section to show (ask, create, ingest, feedback, tips)
                 If None, shows overview with all sections.
    """
    blocks = []

    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Knowledge Base Bot Help",
            "emoji": True,
        },
    })

    if section and section in HELP_SECTIONS:
        # Show specific section
        blocks.extend(_build_section_blocks(section, HELP_SECTIONS[section]))
    else:
        # Show overview
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "I'm your AI-powered knowledge assistant! I can answer questions, "
                    "help you create documentation, and learn from your feedback.\n\n"
                    "*Quick start:* Just mention me with a question!"
                ),
            },
        })

        blocks.append({"type": "divider"})

        # Add each section as a summary
        for key, section_data in HELP_SECTIONS.items():
            if key == "tips":
                continue  # Tips shown at the end

            icon = section_data.get("icon", "bookmark")
            title = section_data.get("title", key.title())

            # Get first command as example
            commands = section_data.get("commands", [])
            example = ""
            if commands:
                example = f"\n_Example: `{commands[0].get('examples', [''])[0]}`_" if commands[0].get("examples") else ""

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":{icon}: *{title}*{example}",
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Learn more",
                        "emoji": True,
                    },
                    "action_id": f"help_section_{key}",
                    "value": key,
                },
            })

        # Tips section
        blocks.append({"type": "divider"})

        tips = HELP_SECTIONS["tips"]["tips"]
        tips_text = "\n".join([f"• {tip}" for tip in tips[:3]])

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":star2: *Pro Tips*\n{tips_text}",
            },
        })

        # Footer with commands list
        blocks.append({"type": "divider"})

        from knowledge_base.config import settings
        p = settings.SLACK_COMMAND_PREFIX
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"*Commands:* `/{p}help` • `/{p}create-knowledge` • `/{p}create-doc` • `/{p}ingest-doc`\n"
                        "*Shortcuts:* `@bot <question>` • `Save as Doc` (message menu)"
                    ),
                },
            ],
        })

    return blocks


def _build_section_blocks(key: str, section: dict) -> list[dict]:
    """Build detailed blocks for a specific section."""
    blocks = []

    icon = section.get("icon", "bookmark")
    title = section.get("title", key.title())

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f":{icon}: *{title}*",
        },
    })

    blocks.append({"type": "divider"})

    # Commands
    for cmd in section.get("commands", []):
        usage = cmd.get("usage", "")
        description = cmd.get("description", "")
        examples = cmd.get("examples", [])
        options = cmd.get("options", [])
        supported = cmd.get("supported", [])

        text_parts = [f"*`{usage}`*", description]

        if examples:
            examples_text = "\n".join([f"  • `{ex}`" for ex in examples])
            text_parts.append(f"\n_Examples:_\n{examples_text}")

        if options:
            options_text = "\n".join([f"  :{emoji}: {desc}" for emoji, desc in options])
            text_parts.append(f"\n{options_text}")

        if supported:
            supported_text = " • ".join(supported)
            text_parts.append(f"\n_Supported:_ {supported_text}")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(text_parts),
            },
        })

    # Tips section special handling
    for tip in section.get("tips", []):
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":point_right: {tip}",
            },
        })

    # Back button
    blocks.append({"type": "divider"})

    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Back to Overview",
                    "emoji": True,
                },
                "action_id": "help_back_overview",
            },
        ],
    })

    return blocks


async def handle_help_command(ack: Any, command: dict, client: WebClient) -> None:
    """Handle the /help slash command."""
    await ack()

    user_id = command.get("user_id")
    channel_id = command.get("channel_id")
    section = command.get("text", "").strip().lower() or None

    # Validate section
    if section and section not in HELP_SECTIONS:
        section = None

    blocks = build_help_blocks(section)

    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        blocks=blocks,
        text="Knowledge Base Bot Help",
    )


async def handle_help_section_click(ack: Any, body: dict, client: WebClient) -> None:
    """Handle clicking a 'Learn more' button in help."""
    await ack()

    action = body["actions"][0]
    section = action.get("value", "")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]

    if section in HELP_SECTIONS:
        blocks = build_help_blocks(section)

        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            blocks=blocks,
            text=f"Help: {HELP_SECTIONS[section]['title']}",
        )


async def handle_help_back(ack: Any, body: dict, client: WebClient) -> None:
    """Handle clicking 'Back to Overview' in help."""
    await ack()

    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]

    blocks = build_help_blocks()

    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        blocks=blocks,
        text="Knowledge Base Bot Help",
    )


def register_help_handlers(app):
    """Register help command and action handlers."""
    import re

    from knowledge_base.config import settings
    cmd = f"/{settings.SLACK_COMMAND_PREFIX}help"
    app.command(cmd)(handle_help_command)
    app.action(re.compile(r"help_section_.*"))(handle_help_section_click)
    app.action("help_back_overview")(handle_help_back)
    logger.info(f"Registered slash command: {cmd}")
