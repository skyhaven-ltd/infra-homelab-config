from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Classification:
    item_type: str
    source: str
    confident: bool


KEYWORDS = {
    "Bug": ("bug", "broken", "error", "fail", "fix", "regression", "wrong"),
    "Feature": ("add", "build", "create", "feature", "new", "support"),
    "Task": ("audit", "document", "investigate", "research", "review", "update"),
}


def classify(
    idea: str, supported_types: tuple[str, ...], explicit_type: str = ""
) -> Classification:
    supported = {value.casefold(): value for value in supported_types}
    explicit = explicit_type.strip()
    if explicit:
        match = supported.get(explicit.casefold())
        if match is None:
            raise ValueError("Unsupported item type")
        return Classification(match, "explicit", True)

    words = {word.strip(".,:;!?()[]{}\"'").casefold() for word in idea.split()}
    scores = {
        item_type: sum(keyword in words for keyword in keywords)
        for item_type, keywords in KEYWORDS.items()
        if item_type.casefold() in supported
    }
    if scores:
        best_score = max(scores.values())
        winners = [
            item_type for item_type, score in scores.items() if score == best_score
        ]
        if best_score > 0 and len(winners) == 1:
            return Classification(supported[winners[0].casefold()], "inferred", True)

    fallback = supported.get("task") or next(iter(supported.values()), "")
    if not fallback:
        raise ValueError("Target does not support any item types")
    return Classification(fallback, "fallback", False)
