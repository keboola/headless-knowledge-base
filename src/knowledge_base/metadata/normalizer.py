"""Vocabulary normalization for metadata."""

import re


# Topic synonyms mapping to canonical forms
TOPIC_SYNONYMS: dict[str, list[str]] = {
    "engineering": ["engineers", "eng", "development", "dev", "tech", "technical"],
    "onboarding": ["new hire", "new employee", "getting started", "first day", "orientation"],
    "benefits": ["perks", "compensation", "salary", "bonus", "insurance"],
    "security": ["cybersecurity", "infosec", "privacy", "data protection"],
    "hr": ["human resources", "people ops", "people operations"],
    "sales": ["revenue", "deals", "pipeline", "selling"],
    "product": ["product management", "pm", "roadmap"],
    "finance": ["accounting", "budget", "expenses", "financial"],
    "marketing": ["branding", "content marketing", "advertising"],
    "support": ["customer support", "customer service", "help desk"],
    "policy": ["policies", "guidelines", "rules", "regulations"],
    "vacation": ["time off", "pto", "leave", "holiday"],
    "training": ["learning", "education", "development", "courses"],
    "communication": ["slack", "email", "meetings", "collaboration"],
    "tools": ["software", "applications", "platforms", "systems"],
}

# Canonical audience values
AUDIENCE_CANONICAL = [
    "all_employees",
    "engineering",
    "sales",
    "hr",
    "leadership",
    "new_hires",
    "managers",
    "finance",
    "marketing",
    "support",
    "product",
]

# Valid document types
DOC_TYPES = [
    "policy",
    "how-to",
    "reference",
    "FAQ",
    "announcement",
    "meeting-notes",
    "general",
]

# Valid complexity levels
COMPLEXITY_LEVELS = ["beginner", "intermediate", "advanced"]


class VocabularyNormalizer:
    """Normalizes vocabulary to canonical forms."""

    def __init__(
        self,
        topic_synonyms: dict[str, list[str]] | None = None,
        audience_canonical: list[str] | None = None,
    ):
        self.topic_synonyms = topic_synonyms or TOPIC_SYNONYMS
        self.audience_canonical = audience_canonical or AUDIENCE_CANONICAL
        # Build reverse mapping for topics
        self._topic_reverse: dict[str, str] = {}
        for canonical, synonyms in self.topic_synonyms.items():
            self._topic_reverse[canonical.lower()] = canonical
            for syn in synonyms:
                self._topic_reverse[syn.lower()] = canonical

    def normalize_topics(self, raw_topics: list[str]) -> list[str]:
        """Normalize topics to canonical forms."""
        normalized = []
        seen = set()
        for topic in raw_topics:
            topic_lower = topic.lower().strip()
            # Check if it maps to a canonical form
            canonical = self._topic_reverse.get(topic_lower)
            if canonical and canonical not in seen:
                normalized.append(canonical)
                seen.add(canonical)
            elif topic_lower not in seen:
                # Keep original if not in mapping
                normalized.append(topic.strip())
                seen.add(topic_lower)
        return normalized[:5]  # Limit to 5 topics

    def normalize_audience(self, raw_audience: list[str]) -> list[str]:
        """Normalize audience to canonical values."""
        normalized = []
        seen = set()
        for audience in raw_audience:
            audience_clean = self._normalize_audience_value(audience)
            if audience_clean and audience_clean not in seen:
                normalized.append(audience_clean)
                seen.add(audience_clean)
        return normalized

    def _normalize_audience_value(self, value: str) -> str | None:
        """Map a single audience value to canonical form."""
        value_lower = value.lower().strip()
        value_normalized = re.sub(r"[_\s-]+", "_", value_lower)

        # Direct match
        if value_normalized in self.audience_canonical:
            return value_normalized

        # Common mappings
        mappings = {
            "everyone": "all_employees",
            "all": "all_employees",
            "engineers": "engineering",
            "developers": "engineering",
            "dev": "engineering",
            "eng": "engineering",
            "tech": "engineering",
            "technical": "engineering",
            "new employees": "new_hires",
            "new hire": "new_hires",
            "newcomers": "new_hires",
            "manager": "managers",
            "management": "managers",
            "leader": "leadership",
            "leaders": "leadership",
            "executives": "leadership",
            "sales team": "sales",
            "hr team": "hr",
            "human resources": "hr",
            "finance team": "finance",
            "marketing team": "marketing",
            "support team": "support",
            "product team": "product",
        }

        return mappings.get(value_normalized, value_normalized)

    def normalize_doc_type(self, doc_type: str) -> str:
        """Normalize document type."""
        doc_type_lower = doc_type.lower().strip()
        doc_type_normalized = doc_type_lower.replace(" ", "-")

        if doc_type_normalized in DOC_TYPES:
            return doc_type_normalized

        # Common mappings
        mappings = {
            "guide": "how-to",
            "tutorial": "how-to",
            "instructions": "how-to",
            "manual": "reference",
            "documentation": "reference",
            "docs": "reference",
            "faq": "FAQ",
            "faqs": "FAQ",
            "questions": "FAQ",
            "news": "announcement",
            "update": "announcement",
            "newsletter": "announcement",
            "notes": "meeting-notes",
            "minutes": "meeting-notes",
            "summary": "meeting-notes",
        }

        return mappings.get(doc_type_normalized, "general")

    def normalize_complexity(self, complexity: str) -> str:
        """Normalize complexity level."""
        complexity_lower = complexity.lower().strip()

        if complexity_lower in COMPLEXITY_LEVELS:
            return complexity_lower

        # Common mappings
        mappings = {
            "basic": "beginner",
            "easy": "beginner",
            "simple": "beginner",
            "medium": "intermediate",
            "moderate": "intermediate",
            "normal": "intermediate",
            "complex": "advanced",
            "expert": "advanced",
            "difficult": "advanced",
        }

        return mappings.get(complexity_lower, "intermediate")
