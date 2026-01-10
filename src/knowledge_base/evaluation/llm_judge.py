"""LLM-as-Judge for evaluating RAG response quality."""

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge_base.rag.llm import BaseLLM

logger = logging.getLogger(__name__)


@dataclass
class EvaluationScores:
    """Evaluation scores from LLM judge."""

    groundedness: float
    relevance: float
    completeness: float

    @property
    def overall(self) -> float:
        """Calculate overall score as average."""
        return (self.groundedness + self.relevance + self.completeness) / 3


GROUNDEDNESS_PROMPT = """Evaluate if this answer is fully supported by the provided documents.

Documents:
{documents}

Answer:
{answer}

Score from 0.0 (not grounded, contains made-up info) to 1.0 (fully grounded).
Only return the numeric score as a decimal number, nothing else."""

RELEVANCE_PROMPT = """Evaluate if these documents are relevant to the question.

Question: {query}

Documents:
{documents}

Score from 0.0 (completely irrelevant) to 1.0 (highly relevant).
Only return the numeric score as a decimal number, nothing else."""

COMPLETENESS_PROMPT = """Evaluate if this answer fully addresses the question.

Question: {query}

Answer:
{answer}

Score from 0.0 (doesn't address at all) to 1.0 (fully addresses).
Only return the numeric score as a decimal number, nothing else."""


class LLMJudge:
    """Use LLM to evaluate RAG response quality."""

    def __init__(self, llm: "BaseLLM"):
        """Initialize LLM judge.

        Args:
            llm: LLM instance for evaluation
        """
        self.llm = llm

    async def evaluate(
        self,
        query: str,
        answer: str,
        documents: list[str],
    ) -> EvaluationScores:
        """Evaluate a query-answer pair.

        Args:
            query: Original user query
            answer: Generated answer
            documents: Retrieved documents used to generate answer

        Returns:
            EvaluationScores with all metrics
        """
        # Evaluate all three metrics
        groundedness = await self.evaluate_groundedness(answer, documents)
        relevance = await self.evaluate_relevance(query, documents)
        completeness = await self.evaluate_completeness(query, answer)

        return EvaluationScores(
            groundedness=groundedness,
            relevance=relevance,
            completeness=completeness,
        )

    async def evaluate_groundedness(
        self, answer: str, documents: list[str]
    ) -> float:
        """Check if answer is grounded in documents.

        Args:
            answer: Generated answer
            documents: Source documents

        Returns:
            Score from 0.0 to 1.0
        """
        if not documents:
            return 0.0

        docs_text = self._format_docs(documents)
        prompt = GROUNDEDNESS_PROMPT.format(documents=docs_text, answer=answer)

        return await self._get_score(prompt, default=0.5)

    async def evaluate_relevance(
        self, query: str, documents: list[str]
    ) -> float:
        """Check if retrieved documents are relevant to query.

        Args:
            query: Original query
            documents: Retrieved documents

        Returns:
            Score from 0.0 to 1.0
        """
        if not documents:
            return 0.0

        docs_text = self._format_docs(documents)
        prompt = RELEVANCE_PROMPT.format(query=query, documents=docs_text)

        return await self._get_score(prompt, default=0.5)

    async def evaluate_completeness(
        self, query: str, answer: str
    ) -> float:
        """Check if answer fully addresses the query.

        Args:
            query: Original query
            answer: Generated answer

        Returns:
            Score from 0.0 to 1.0
        """
        if not answer or not answer.strip():
            return 0.0

        prompt = COMPLETENESS_PROMPT.format(query=query, answer=answer)

        return await self._get_score(prompt, default=0.5)

    def _format_docs(self, documents: list[str], max_length: int = 4000) -> str:
        """Format documents for inclusion in prompt.

        Args:
            documents: List of document contents
            max_length: Maximum total length

        Returns:
            Formatted document string
        """
        formatted = []
        total_length = 0

        for i, doc in enumerate(documents, 1):
            doc_text = f"[Document {i}]\n{doc}\n"
            if total_length + len(doc_text) > max_length:
                # Truncate this document
                remaining = max_length - total_length - 50
                if remaining > 100:
                    doc_text = f"[Document {i}]\n{doc[:remaining]}...\n"
                    formatted.append(doc_text)
                break
            formatted.append(doc_text)
            total_length += len(doc_text)

        return "\n".join(formatted)

    async def _get_score(self, prompt: str, default: float = 0.5) -> float:
        """Get numeric score from LLM response.

        Args:
            prompt: Evaluation prompt
            default: Default score if parsing fails

        Returns:
            Score from 0.0 to 1.0
        """
        try:
            response = await self.llm.generate(prompt)
            score = self._parse_score(response)
            return score

        except Exception as e:
            logger.warning(f"Failed to get evaluation score: {e}")
            return default

    def _parse_score(self, response: str) -> float:
        """Parse numeric score from LLM response.

        Args:
            response: LLM response text

        Returns:
            Parsed score clamped to 0.0-1.0
        """
        # Clean response
        text = response.strip()

        # Try to find a decimal number
        match = re.search(r"(\d+\.?\d*)", text)
        if match:
            score = float(match.group(1))
            # Clamp to 0.0-1.0
            return max(0.0, min(1.0, score))

        logger.warning(f"Could not parse score from: {text}")
        return 0.5
