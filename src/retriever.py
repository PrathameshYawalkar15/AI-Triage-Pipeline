from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from src.ingest import load_runbooks
from src.schemas import EvidenceCitation

STOPWORDS = {
    "the", "a", "an", "and", "or", "in", "on", "of", "to", "for", "with",
    "is", "are", "was", "were", "be", "by", "at", "from", "as", "that", "this",
}


class RetrievedChunk(BaseModel):
    doc_id: str
    source: str
    text: str
    score: float = Field(ge=0.0, le=1.0)
    matched_terms: list[str] = Field(default_factory=list)


class RetrievalGrade(BaseModel):
    is_sufficient: bool
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    refined_query: str | None = None


def _extract_keywords(text: str) -> set[str]:
    """Split text into lowercase words and drop common filler words."""
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


class RunbookRetriever:
    """Simple keyword-based retriever and evidence grader for Markdown runbooks."""

    def __init__(self, runbooks_dir: Path) -> None:
        self.docs = load_runbooks(runbooks_dir)

    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        """Score each runbook section by how many query keywords it contains."""
        query_words = _extract_keywords(query)
        if not query_words:
            return []

        results: list[RetrievedChunk] = []
        for doc in self.docs:
            doc_words = _extract_keywords(doc["text"])
            matched = sorted(query_words & doc_words)
            if not matched:
                continue

            score = round(len(matched) / len(query_words), 2)
            results.append(
                RetrievedChunk(
                    doc_id=doc["doc_id"],
                    source=doc["source"],
                    text=doc["text"],
                    score=score,
                    matched_terms=matched,
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def grade_evidence(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        min_score: float = 0.25,
    ) -> RetrievalGrade:
        """Check if the top runbook match is strong enough, or suggest a retry query."""
        if not chunks:
            return RetrievalGrade(
                is_sufficient=False,
                confidence=0.0,
                rationale="No runbook sections matched the query.",
                refined_query=self._simplify_query(query),
            )

        top = chunks[0]
        if top.score >= min_score:
            return RetrievalGrade(
                is_sufficient=True,
                confidence=min(1.0, round(top.score + 0.2, 2)),
                rationale=f"Matched {top.source} ({top.doc_id}) on: {', '.join(top.matched_terms)}.",
                refined_query=None,
            )

        return RetrievalGrade(
            is_sufficient=False,
            confidence=top.score,
            rationale=f"Top match ({top.source}, score={top.score}) is too weak. Retrying with key terms.",
            refined_query=self._simplify_query(query),
        )

    @staticmethod
    def _simplify_query(query: str) -> str:
        """Keep only the longest, most specific technical words for a retry search."""
        words = sorted(_extract_keywords(query), key=len, reverse=True)
        return " ".join(words[:4])

    @staticmethod
    def to_citations(chunks: list[RetrievedChunk]) -> list[EvidenceCitation]:
        """Convert retrieved runbook chunks into EvidenceCitation records."""
        return [
            EvidenceCitation(
                source_type="runbook",
                source_id=chunk.doc_id,
                snippet=chunk.text.splitlines()[0][:160],
                relevance_note=f"Matched terms: {', '.join(chunk.matched_terms)}",
            )
            for chunk in chunks
        ]