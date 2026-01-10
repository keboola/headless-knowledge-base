"""Slack bot integration for knowledge base."""

from knowledge_base.slack.bot import create_app, run_bot
from knowledge_base.slack.doc_creation import register_doc_handlers
from knowledge_base.slack.quick_knowledge import register_quick_knowledge_handler
from knowledge_base.slack.help_command import register_help_handlers
from knowledge_base.slack.ingest_doc import register_ingest_handler
from knowledge_base.slack.admin_escalation import register_escalation_handlers

__all__ = [
    "create_app",
    "run_bot",
    "register_doc_handlers",
    "register_quick_knowledge_handler",
    "register_help_handlers",
    "register_ingest_handler",
    "register_escalation_handlers",
]
