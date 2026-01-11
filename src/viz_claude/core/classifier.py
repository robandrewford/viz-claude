"""Classification using local heuristics and optional Claude API."""

from __future__ import annotations

import fnmatch
import logging
import re
from typing import TYPE_CHECKING

from . import Classification, ClassificationState, UserPreferences

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# =============================================================================
# Heuristic Classifier (No API Required)
# =============================================================================


class HeuristicClassifier:
    """
    Classify conversations using local heuristics.
    
    Fast, deterministic, no API calls. Good enough for MVP.
    """

    # Tool -> Category mappings (strongest signals)
    TOOL_SIGNALS: dict[str, list[tuple[re.Pattern[str], str, float]]] = {
        "bash": [
            (re.compile(r"docker|kubectl|k8s|terraform|aws|gcloud", re.I), "cloud--compute", 0.85),
            (re.compile(r"pip|conda|python.*train|torch|tensorflow", re.I), "ml--training", 0.80),
            (re.compile(r"psql|mysql|sqlite|mongo|redis", re.I), "data--structure", 0.80),
            (re.compile(r"git|npm|yarn|cargo|make|cmake", re.I), "code--systems", 0.75),
            (re.compile(r"curl|wget|http|api", re.I), "cloud--network", 0.70),
            (re.compile(r"grep|sed|awk|find|ls|cat", re.I), "code--craft", 0.60),
        ],
        "edit": [
            (re.compile(r"\.py$", re.I), "code--craft", 0.70),
            (re.compile(r"\.sql$", re.I), "data--structure", 0.75),
            (re.compile(r"\.ya?ml$|\.tf$|dockerfile", re.I), "cloud--compute", 0.70),
            (re.compile(r"\.md$|\.txt$|\.rst$", re.I), "writing--technical", 0.65),
            (re.compile(r"\.json$|\.csv$", re.I), "data--flow", 0.60),
        ],
        "read": [
            (re.compile(r"\.py$", re.I), "code--craft", 0.50),
            (re.compile(r"\.sql$", re.I), "data--structure", 0.55),
        ],
        "web_search": [
            (re.compile(r".*"), "research--explore", 0.60),
        ],
    }

    # Content keyword signals (weaker than tools)
    CONTENT_SIGNALS: list[tuple[re.Pattern[str], str, float]] = [
        # ML
        (re.compile(r"train|epoch|loss|gradient|backprop|model|neural|lstm|transformer", re.I), "ml--training", 0.65),
        (re.compile(r"inference|predict|deploy.*model|serve.*model", re.I), "ml--inference", 0.65),
        
        # Data
        (re.compile(r"etl|pipeline|airflow|dagster|prefect|ingest", re.I), "data--flow", 0.70),
        (re.compile(r"schema|table|column|foreign.key|index|normali[zs]", re.I), "data--structure", 0.70),
        (re.compile(r"dashboard|chart|visuali[zs]|metric|report|analytics", re.I), "data--insight", 0.65),
        
        # Cloud
        (re.compile(r"vpc|subnet|route|dns|load.balanc|ingress", re.I), "cloud--network", 0.70),
        (re.compile(r"ec2|lambda|container|kubernetes|ecs|fargate", re.I), "cloud--compute", 0.70),
        (re.compile(r"s3|bucket|blob|storage|cache|redis|dynamo", re.I), "cloud--storage", 0.70),
        
        # Code
        (re.compile(r"architect|design.pattern|microservice|monolith|api.design", re.I), "code--systems", 0.70),
        (re.compile(r"refactor|debug|fix|bug|review|test|lint", re.I), "code--craft", 0.65),
        (re.compile(r"algorithm|complexity|big.o|recursion|dynamic.program", re.I), "code--logic", 0.70),
        
        # Writing
        (re.compile(r"document|readme|spec|rfc|adr|proposal", re.I), "writing--technical", 0.65),
        (re.compile(r"story|narrative|creative|poem|fiction", re.I), "writing--creative", 0.70),
        
        # Research
        (re.compile(r"research|investigate|explore|learn|understand", re.I), "research--explore", 0.55),
        (re.compile(r"summari[zs]e|synthesi[zs]e|compare|decision|recommend", re.I), "research--synthesize", 0.60),
    ]

    DEFAULT_CATEGORY = "conversation--casual"

    def __init__(self, preferences: UserPreferences | None = None):
        """
        Initialize classifier.
        
        Args:
            preferences: User preferences for category filtering
        """
        self.preferences = preferences or UserPreferences()
        self._tool_history: list[tuple[str, str]] = []  # (tool, snippet)
        self._content_samples: list[str] = []

    def add_tool_use(self, tool: str, snippet: str) -> None:
        """Record a tool use for classification."""
        self._tool_history.append((tool, snippet))
        # Keep bounded
        if len(self._tool_history) > 50:
            self._tool_history = self._tool_history[-30:]

    def add_content(self, content: str) -> None:
        """Record content for classification."""
        # Keep last 2000 chars across samples
        self._content_samples.append(content[:500])
        total_len = sum(len(s) for s in self._content_samples)
        while total_len > 2000 and len(self._content_samples) > 1:
            removed = self._content_samples.pop(0)
            total_len -= len(removed)

    def classify(self) -> Classification:
        """
        Classify based on accumulated signals.
        
        Returns:
            Classification result
        """
        candidates: dict[str, tuple[float, list[str]]] = {}

        # Process tool signals (strongest)
        for tool, snippet in self._tool_history:
            tool_key = tool.lower()
            if tool_key in self.TOOL_SIGNALS:
                for pattern, category, weight in self.TOOL_SIGNALS[tool_key]:
                    if pattern.search(snippet):
                        if category not in candidates:
                            candidates[category] = (0.0, [])
                        score, signals = candidates[category]
                        candidates[category] = (
                            min(1.0, score + weight * 0.2),
                            signals + [f"tool:{tool}"]
                        )

        # Process content signals (weaker)
        all_content = " ".join(self._content_samples)
        for pattern, category, weight in self.CONTENT_SIGNALS:
            if pattern.search(all_content):
                if category not in candidates:
                    candidates[category] = (0.0, [])
                score, signals = candidates[category]
                match = pattern.search(all_content)
                signal = match.group(0)[:20] if match else "content"
                candidates[category] = (
                    min(1.0, score + weight * 0.15),
                    signals + [f"kw:{signal}"]
                )

        # Apply preferences
        candidates = self._apply_preferences(candidates)

        # Select best
        if not candidates:
            return Classification(
                category=self.DEFAULT_CATEGORY,
                confidence=0.3,
                signals=["default"],
            )

        best_category = max(candidates, key=lambda c: candidates[c][0])
        score, signals = candidates[best_category]

        # Deduplicate signals
        unique_signals = list(dict.fromkeys(signals))[:5]

        return Classification(
            category=best_category,
            confidence=min(0.95, score),
            signals=unique_signals,
            alternative=self._get_alternative(candidates, best_category),
        )

    def _apply_preferences(
        self, candidates: dict[str, tuple[float, list[str]]]
    ) -> dict[str, tuple[float, list[str]]]:
        """Apply user preferences to candidate scores."""
        result = {}

        for category, (score, signals) in candidates.items():
            # Filter avoided categories
            if any(fnmatch.fnmatch(category, p) for p in self.preferences.avoid_categories):
                continue

            # Boost preferred categories
            if any(fnmatch.fnmatch(category, p) for p in self.preferences.prefer_categories):
                score = min(1.0, score * 1.2)

            result[category] = (score, signals)

        return result

    def _get_alternative(
        self, candidates: dict[str, tuple[float, list[str]]], best: str
    ) -> str | None:
        """Get second-best category."""
        others = [(c, s) for c, (s, _) in candidates.items() if c != best]
        if not others:
            return None
        others.sort(key=lambda x: x[1], reverse=True)
        return others[0][0] if others[0][1] > 0.3 else None

    def reset(self) -> None:
        """Reset accumulated signals."""
        self._tool_history.clear()
        self._content_samples.clear()


# =============================================================================
# Classification State Machine
# =============================================================================


class ClassificationStateMachine:
    """
    Manage classification state transitions.
    
    States:
    - UNCLASSIFIED: No classification yet
    - TENTATIVE: Initial classification, re-evaluate frequently
    - FALLBACK: Low confidence, using parent category
    - ACCEPTED: Medium confidence, re-evaluate occasionally
    - LOCKED: High confidence, re-evaluate rarely
    """

    THRESHOLDS = {
        ClassificationState.UNCLASSIFIED: 3,
        ClassificationState.TENTATIVE: 3,
        ClassificationState.FALLBACK: 3,
        ClassificationState.ACCEPTED: 5,
        ClassificationState.LOCKED: 10,
    }

    def __init__(self) -> None:
        self.state = ClassificationState.UNCLASSIFIED
        self.messages_since_classification = 0
        self.current_classification: Classification | None = None

    def should_classify(self) -> bool:
        """Check if classification is needed."""
        threshold = self.THRESHOLDS.get(self.state, 5)
        return self.messages_since_classification >= threshold

    def on_message(self) -> None:
        """Record that a message was processed."""
        self.messages_since_classification += 1

    def on_classification(self, classification: Classification) -> ClassificationState:
        """
        Process a new classification result.
        
        Returns:
            New state
        """
        self.current_classification = classification
        self.messages_since_classification = 0

        # Determine new state based on confidence
        if classification.confidence >= 0.8:
            self.state = ClassificationState.LOCKED
        elif classification.confidence >= 0.6:
            self.state = ClassificationState.ACCEPTED
        elif classification.confidence >= 0.4:
            self.state = ClassificationState.TENTATIVE
        else:
            self.state = ClassificationState.FALLBACK

        return self.state

    def force_reclassify(self) -> None:
        """Force next classification check."""
        self.messages_since_classification = 999

    def reset(self) -> None:
        """Reset to initial state."""
        self.state = ClassificationState.UNCLASSIFIED
        self.messages_since_classification = 0
        self.current_classification = None


# =============================================================================
# Optional: API-Based Classifier (Phase 2)
# =============================================================================


CLASSIFICATION_PROMPT = """Classify this conversation into exactly one category.

CATEGORIES:
{categories}

RECENT ACTIVITY:
Tools used: {tools}
Content sample: {content}

Respond with JSON only:
{{"category": "category--subcategory", "confidence": 0.0-1.0, "signals": ["signal1", "signal2"]}}"""


async def classify_with_api(
    client: "AsyncAnthropic",  # type: ignore[name-defined]
    tools: list[tuple[str, str]],
    content: str,
    categories: list[str],
) -> Classification:
    """
    Classify using Claude API (optional, for higher accuracy).
    
    Args:
        client: Anthropic async client
        tools: List of (tool_name, snippet) tuples
        content: Content sample
        categories: Available categories
        
    Returns:
        Classification result
    """
    import json

    prompt = CLASSIFICATION_PROMPT.format(
        categories="\n".join(f"- {c}" for c in categories),
        tools=", ".join(f"{t}({s[:50]})" for t, s in tools[-5:]) or "none",
        content=content[:500] or "none",
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )

        result = json.loads(response.content[0].text)
        return Classification(
            category=result.get("category", "conversation--casual"),
            confidence=float(result.get("confidence", 0.5)),
            signals=result.get("signals", []),
        )
    except Exception as e:
        logger.error(f"API classification failed: {e}")
        return Classification(
            category="conversation--casual",
            confidence=0.0,
            signals=["api_error"],
        )
