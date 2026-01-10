"""AI-powered document drafting from descriptions and thread summaries."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from knowledge_base.documents.models import (
    Classification,
    DocumentArea,
    DocumentDraft,
    DocumentType,
    SourceType,
)

if TYPE_CHECKING:
    from knowledge_base.llm.base import BaseLLM


@dataclass
class DraftResult:
    """Result of AI drafting."""

    draft: DocumentDraft
    confidence: float
    suggestions: list[str]


class AIDrafter:
    """AI-powered document drafter.

    Uses LLM to generate document content from:
    - Simple descriptions
    - Slack thread summaries
    - Existing document updates
    """

    def __init__(self, llm: "BaseLLM"):
        """Initialize the drafter.

        Args:
            llm: Language model for content generation
        """
        self.llm = llm

    async def draft_from_description(
        self,
        title: str,
        description: str,
        area: DocumentArea | str,
        doc_type: DocumentType | str,
        classification: Classification | str = Classification.INTERNAL,
    ) -> DraftResult:
        """Create a document draft from a description.

        Args:
            title: Document title
            description: What the document should cover
            area: Document area (people, finance, etc.)
            doc_type: Type of document (policy, procedure, etc.)
            classification: Security classification

        Returns:
            DraftResult with generated content
        """
        # Convert strings to enums
        if isinstance(area, str):
            area = DocumentArea(area)
        if isinstance(doc_type, str):
            doc_type = DocumentType(doc_type)
        if isinstance(classification, str):
            classification = Classification(classification)

        prompt = self._build_draft_prompt(title, description, area, doc_type)
        content = await self.llm.generate(prompt)

        # Parse suggestions from content if present
        content, suggestions = self._extract_suggestions(content)

        draft = DocumentDraft(
            title=title,
            content=content,
            area=area,
            doc_type=doc_type,
            classification=classification,
            source_type=SourceType.AI_DRAFT,
        )

        return DraftResult(
            draft=draft,
            confidence=0.8,  # Default confidence for AI drafts
            suggestions=suggestions,
        )

    async def draft_from_thread(
        self,
        thread_messages: list[dict],
        channel_id: str,
        thread_ts: str,
        area: DocumentArea | str,
        doc_type: DocumentType | str = DocumentType.INFORMATION,
        classification: Classification | str = Classification.INTERNAL,
    ) -> DraftResult:
        """Create a document draft from a Slack thread.

        Args:
            thread_messages: List of messages from the thread
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            area: Document area
            doc_type: Type of document
            classification: Security classification

        Returns:
            DraftResult with synthesized content
        """
        if isinstance(area, str):
            area = DocumentArea(area)
        if isinstance(doc_type, str):
            doc_type = DocumentType(doc_type)
        if isinstance(classification, str):
            classification = Classification(classification)

        # Format thread for LLM
        thread_text = self._format_thread(thread_messages)
        prompt = self._build_thread_summary_prompt(thread_text, area, doc_type)

        content = await self.llm.generate(prompt)

        # Extract title and content
        title, content = self._extract_title_content(content)
        content, suggestions = self._extract_suggestions(content)

        draft = DocumentDraft(
            title=title,
            content=content,
            area=area,
            doc_type=doc_type,
            classification=classification,
            source_type=SourceType.THREAD_SUMMARY,
            source_thread_ts=thread_ts,
            source_channel_id=channel_id,
        )

        return DraftResult(
            draft=draft,
            confidence=0.7,  # Slightly lower for thread summaries
            suggestions=suggestions,
        )

    async def improve_draft(
        self,
        draft: DocumentDraft,
        feedback: str,
    ) -> DraftResult:
        """Improve a draft based on feedback.

        Args:
            draft: Existing draft to improve
            feedback: User feedback on what to change

        Returns:
            DraftResult with improved content
        """
        prompt = self._build_improvement_prompt(draft, feedback)
        content = await self.llm.generate(prompt)
        content, suggestions = self._extract_suggestions(content)

        improved_draft = DocumentDraft(
            title=draft.title,
            content=content,
            area=draft.area,
            doc_type=draft.doc_type,
            classification=draft.classification,
            source_type=draft.source_type,
            source_thread_ts=draft.source_thread_ts,
            source_channel_id=draft.source_channel_id,
        )

        return DraftResult(
            draft=improved_draft,
            confidence=0.85,  # Higher after improvement
            suggestions=suggestions,
        )

    def _build_draft_prompt(
        self,
        title: str,
        description: str,
        area: DocumentArea,
        doc_type: DocumentType,
    ) -> str:
        """Build prompt for document drafting."""
        doc_type_guidance = {
            DocumentType.POLICY: (
                "This is a POLICY document. Use formal language, clear directives, "
                "and include sections for: Purpose, Scope, Policy Statement, "
                "Responsibilities, and Compliance."
            ),
            DocumentType.PROCEDURE: (
                "This is a PROCEDURE document. Include step-by-step instructions, "
                "prerequisites, expected outcomes, and troubleshooting tips."
            ),
            DocumentType.GUIDELINE: (
                "This is a GUIDELINE document. Provide recommendations and best "
                "practices. Use 'should' rather than 'must' language."
            ),
            DocumentType.INFORMATION: (
                "This is an INFORMATION document. Provide clear, factual content "
                "organized logically. Include relevant context and examples."
            ),
        }

        return f"""Create a professional {doc_type.value} document for the {area.value} area.

Title: {title}

Description of what to cover:
{description}

{doc_type_guidance.get(doc_type, '')}

Format the document in Confluence-compatible markdown with:
- Clear headings (use ## for sections)
- Bullet points where appropriate
- Tables if needed for structured data
- Clear, concise language

Generate ONLY the document content, no meta-commentary."""

    def _build_thread_summary_prompt(
        self,
        thread_text: str,
        area: DocumentArea,
        doc_type: DocumentType,
    ) -> str:
        """Build prompt for thread summarization."""
        return f"""Summarize the following Slack conversation into a {doc_type.value} document for the {area.value} area.

Conversation:
{thread_text}

Create a well-structured document that:
1. Captures the key information and decisions from the conversation
2. Organizes content logically under appropriate headings
3. Removes conversational elements and focuses on actionable information
4. Uses professional language appropriate for documentation

Start with a title line formatted as: # Title
Then provide the document content.

If any important details are missing or unclear, add a "Suggestions" section at the end listing what should be clarified."""

    def _build_improvement_prompt(
        self,
        draft: DocumentDraft,
        feedback: str,
    ) -> str:
        """Build prompt for draft improvement."""
        return f"""Improve the following {draft.doc_type.value} document based on the feedback provided.

Current document:
# {draft.title}

{draft.content}

Feedback to address:
{feedback}

Provide the improved document content. Maintain the same structure and format unless the feedback specifically requests changes to structure."""

    def _format_thread(self, messages: list[dict]) -> str:
        """Format Slack thread messages for LLM."""
        formatted = []
        for msg in messages:
            user = msg.get("user", "Unknown")
            text = msg.get("text", "")
            formatted.append(f"[{user}]: {text}")
        return "\n".join(formatted)

    def _extract_title_content(self, text: str) -> tuple[str, str]:
        """Extract title and content from generated text."""
        lines = text.strip().split("\n")
        title = "Untitled Document"
        content_start = 0

        for i, line in enumerate(lines):
            if line.startswith("# "):
                title = line[2:].strip()
                content_start = i + 1
                break

        content = "\n".join(lines[content_start:]).strip()
        return title, content

    def _extract_suggestions(self, content: str) -> tuple[str, list[str]]:
        """Extract suggestions section from content."""
        suggestions = []

        # Look for suggestions section
        lower_content = content.lower()
        markers = ["## suggestions", "### suggestions", "suggestions:"]

        for marker in markers:
            if marker in lower_content:
                idx = lower_content.index(marker)
                main_content = content[:idx].strip()
                suggestions_text = content[idx:].strip()

                # Parse bullet points
                for line in suggestions_text.split("\n")[1:]:
                    line = line.strip()
                    if line.startswith(("-", "*", "•")):
                        suggestions.append(line[1:].strip())
                    elif line and not line.startswith("#"):
                        suggestions.append(line)

                return main_content, suggestions

        return content, suggestions
