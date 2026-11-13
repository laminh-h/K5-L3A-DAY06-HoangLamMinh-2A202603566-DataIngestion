"""Automatic retrieval metrics (Hit@1, Evidence Hit@3) and per-query traces.

A retrieved chunk is a hit when it belongs to a gold (source, page) AND contains the full
gold evidence quote (case/whitespace-insensitive, after the same normalization as the corpus).
Any documented alternative gold evidence is accepted. Coherence and grounding are NOT inferred
here - they are labelled manually (see results/audit_*.csv).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .ingestion import flatten


def _gold_match(hit: dict[str, Any], gold: dict[str, Any]) -> tuple[bool, bool]:
    meta = hit["metadata"]
    same_page = meta.get("document_id") == gold["source_id"] and int(meta.get("page", -1)) == int(gold["page"])
    contains = flatten(gold["evidence_quote"]) in flatten(hit["text"])
    return same_page and contains, same_page


def filter_respected(hit: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    if not filters:
        return True
    return all(hit["metadata"].get(k) == v for k, v in filters.items())


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    judged = []
    for hit in hits:
        matches = [_gold_match(hit, g) for g in question["gold"]]
        judged.append({
            **hit,
            "evidence_hit": any(m[0] for m in matches),
            "gold_page_match": any(m[1] for m in matches),
            "respects_filter": filter_respected(hit, question.get("filter")),
        })
    return {
        "question_id": question["id"],
        "split": question["split"],
        "type": question.get("type"),
        "question": question["question"],
        "filter": question.get("filter"),
        "expected_answer": question["expected_answer"],
        "gold": question["gold"],
        "hit_at_1": bool(judged and judged[0]["evidence_hit"]),
        "hit_at_3": any(h["evidence_hit"] for h in judged[:3]),
        "gold_page_in_top3": any(h["gold_page_match"] for h in judged[:3]),
        "filter_compliant_top3": all(h["respects_filter"] for h in judged[:3]) if question.get("filter") else None,
        "hits": judged,
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per (strategy, split): counts reported as n/N, not only percentages."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in traces:
        groups[(t["strategy"], t["split"])].append(t)
    out: dict[str, Any] = {}
    for (strategy, split), items in sorted(groups.items()):
        n = len(items)
        h1 = sum(t["hit_at_1"] for t in items)
        h3 = sum(t["hit_at_3"] for t in items)
        filt = [t for t in items if t["filter"]]
        comp = sum(bool(t["filter_compliant_top3"]) for t in filt)
        out.setdefault(strategy, {})[split] = {
            "N": n, "hit_at_1": h1, "hit_at_3": h3,
            "hit_at_1_rate": round(h1 / n, 3) if n else None,
            "hit_at_3_rate": round(h3 / n, 3) if n else None,
            "filter_questions": len(filt),
            "filter_compliant_top3": comp if filt else None,
        }
    return out
