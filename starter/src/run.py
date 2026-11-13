"""Day 06 pipeline entry point.

Run from the `starter/` folder:
    python -m src.run ingest     # read, normalize, chunk (A, B), embed, store; safe to re-run
    python -m src.run verify     # check benchmark gold evidence exists on the gold pages
    python -m src.run evaluate   # top-3 retrieval for A/B/C on all questions, traces + metrics
    python -m src.run audit      # build manual-audit sheets (coherence / metadata / grounding)
    python -m src.run all        # ingest + verify + evaluate + audit
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size, page_text
from .evaluation import evaluate_query, summarize
from .ingestion import IngestLog, flatten, load_corpus, load_manifest, section_for
from .models import Chunk, DocumentPage

ROOT = Path(__file__).resolve().parents[2]
STARTER = ROOT / "starter"
RESULTS = ROOT / "results"
MANIFEST = ROOT / "data" / "manifest.json"
BENCHMARK = ROOT / "benchmark" / "questions.json"

load_dotenv(STARTER / ".env")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL") or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CHROMA_PATH = Path(os.getenv("CHROMA_PATH") or (STARTER / "chroma_db"))
TOP_K = 3

# Index = physical collection. C reuses index B's chunks and vectors; it only adds the filter.
INDEXES: dict[str, dict[str, Any]] = {
    "A": {"chunking": "fixed_size", "size": 500, "overlap": 50},
    "B": {"chunking": "by_paragraph", "max_size": 600},
}
STRATEGIES: dict[str, dict[str, Any]] = {
    "A": {"index": "A", "use_filter": False,
          "description": "Fixed 500-char windows, 50 overlap; source/page/edition/section metadata; no filter"},
    "B": {"index": "B", "use_filter": False,
          "description": "Paragraph-aware chunks (<=600 chars, headings kept with paragraph); same metadata; no filter"},
    "C": {"index": "B", "use_filter": True,
          "description": "Same chunks/vectors as B; metadata pre-filter applied only when the question supplies one"},
}
SELECTION_RULE = ("Chosen before reading test results: highest dev Evidence Hit@3; tie -> higher dev Hit@1; "
                  "tie -> fewer chunks / lower ingest time.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_audit(path: Path, rows: list[dict[str, Any]]) -> None:
    """Never overwrite an audit sheet that already holds manual labels."""
    if path.exists():
        with path.open(encoding="utf-8") as f:
            labelled = any((r.get("label_0_2") or r.get("metadata_complete_and_correct") or "").strip()
                           for r in csv.DictReader(f))
        if labelled:
            path = path.with_name(path.stem + ".new.csv")
            print(f"{path.name}: existing sheet has manual labels - wrote fresh template next to it instead")
    _write_csv(path, rows)


def _embedder():
    from .embeddings import SentenceTransformerEmbedder
    return SentenceTransformerEmbedder(EMBEDDING_MODEL)


def _store(embedder):
    from .store import ChromaStore
    return ChromaStore(CHROMA_PATH, embedder.dimensions, embedder.model_name)


def load_pages() -> tuple[list[DocumentPage], list[dict[str, Any]], IngestLog, dict[str, Any]]:
    manifest = load_manifest(MANIFEST)
    log = IngestLog()
    pages, inventory = load_corpus(ROOT, manifest, log)
    return pages, inventory, log, manifest


def build_chunks(pages: list[DocumentPage], index: str) -> list[Chunk]:
    cfg = INDEXES[index]
    out: list[Chunk] = []
    for page in pages:
        if cfg["chunking"] == "fixed_size":
            out.extend(fixed_size(page, cfg["size"], cfg["overlap"], strategy=index))
        else:
            out.extend(by_paragraph(page, cfg["max_size"], strategy=index))
    return out


def _length_stats(values: list[int]) -> dict[str, Any]:
    s = sorted(values)
    return {"min": s[0], "median": statistics.median(s), "mean": round(statistics.fmean(s), 1),
            "p90": s[int(0.9 * (len(s) - 1))], "max": s[-1], "total": sum(s)}


# --------------------------------------------------------------------------- ingest
def cmd_ingest() -> None:
    t0 = time.perf_counter()
    pages, inventory, log, manifest = load_pages()
    read_seconds = time.perf_counter() - t0
    _write_csv(ROOT / "data" / "page_inventory.csv", inventory)

    counted = [r for r in inventory if r["counted"]]
    thin = [r for r in counted if r["normalized_chars"] < 500]
    print(f"Content pages counted: {len(counted)} (from {len(inventory)} physical pages); "
          f"thin counted pages (<500 chars): {[(r['document_id'], r['page']) for r in thin]}")
    if len(counted) < 30:
        sys.exit("Corpus has fewer than 30 content pages - aborting.")

    t1 = time.perf_counter()
    embedder = _embedder()
    load_seconds = time.perf_counter() - t1
    store = _store(embedder)

    run: dict[str, Any] = {"timestamp": _now(), "read_normalize_seconds": round(read_seconds, 2),
                           "model_load_seconds": round(load_seconds, 2), "indexes": {}}
    for index in INDEXES:
        chunks = build_chunks(pages, index)
        ts = time.perf_counter()
        embedded = deleted = 0
        for doc_id in sorted({c.document_id for c in chunks}):
            doc_chunks = [c for c in chunks if c.document_id == doc_id]
            existing = store.existing(index, doc_id)
            todo = [c for c in doc_chunks if existing.get(c.chunk_id) != c.metadata["content_hash"]]
            stale = sorted(set(existing) - {c.chunk_id for c in doc_chunks})
            if todo:
                store.upsert(index, todo, embedder.embed_documents([c.text for c in todo]))
            store.delete(index, stale)
            embedded += len(todo)
            deleted += len(stale)
        seconds = time.perf_counter() - ts
        tokens = embedder.token_lengths([c.text for c in chunks])
        run["indexes"][index] = {
            "config": INDEXES[index],
            "chunks": len(chunks),
            "chars": _length_stats([len(c.text) for c in chunks]),
            "tokens": _length_stats(tokens),
            "truncated_chunks": sum(t > embedder.max_seq_length for t in tokens),
            "embedded_this_run": embedded,
            "deleted_stale_this_run": deleted,
            "count_in_store_after": store.count(index),
            "embed_and_store_seconds": round(seconds, 2),
        }
        print(f"[{index}] chunks={len(chunks)} embedded_now={embedded} stale_deleted={deleted} "
              f"in_store={store.count(index)} time={seconds:.1f}s truncated(>{embedder.max_seq_length} tok)="
              f"{run['indexes'][index]['truncated_chunks']}")

    report_path = RESULTS / "ingest_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"runs": []}
    report.update({
        "embedding": embedder.describe(),
        "vector_store": _store_info(),
        "corpus": {"physical_pages": len(inventory), "content_pages": len(counted),
                   "content_chars": sum(r["normalized_chars"] for r in counted),
                   "per_document": {s["source_id"]: s["counted_page_total"] for s in manifest["sources"]}},
        "normalization_log": log.to_dict(),
        "cost_usd": 0.0,
    })
    report["runs"].append(run)
    _write_json(report_path, report)


def _store_info() -> dict[str, Any]:
    import chromadb
    return {"name": "Chroma (PersistentClient, local disk)", "version": chromadb.__version__,
            "path": str(CHROMA_PATH.relative_to(ROOT)) if CHROMA_PATH.is_relative_to(ROOT) else str(CHROMA_PATH),
            "collections": {i: f"day6_index_{i}" for i in INDEXES}, "metric": "cosine",
            "search": "approximate (HNSW); metadata 'where' filter applied inside the query"}


# --------------------------------------------------------------------------- verify
def cmd_verify() -> bool:
    pages, _, _, manifest = load_pages()
    by_key = {(p.document_id, p.page): p for p in pages}
    questions = json.loads(BENCHMARK.read_text(encoding="utf-8"))["questions"]
    problems: list[str] = []
    rows = []
    for q in questions:
        for g in q["gold"]:
            page = by_key.get((g["source_id"], int(g["page"])))
            found = bool(page) and flatten(g["evidence_quote"]) in flatten(page.text)
            rows.append({"id": q["id"], "source_id": g["source_id"], "page": g["page"], "found": found})
            if not found:
                problems.append(f"{q['id']}: evidence not found on {g['source_id']} p{g['page']}")
        for key, value in (q.get("filter") or {}).items():
            if not any(p.metadata.get(key) == value for p in pages):
                problems.append(f"{q['id']}: filter {key}={value!r} matches no page")
    dev = [q for q in questions if q["split"] == "dev"]
    test = [q for q in questions if q["split"] == "test"]
    filt = [q for q in questions if q.get("filter")]
    checks = {
        "questions": len(questions), "dev": len(dev), "test": len(test),
        "filter_questions": len(filt), "filter_questions_test": sum(q["split"] == "test" for q in filt),
        "unique_ids": len({q["id"] for q in questions}) == len(questions),
    }
    if len(questions) < 20 or len(dev) < 15 or len(test) < 5:
        problems.append(f"split too small: {checks}")
    if len(filt) < 3 or checks["filter_questions_test"] < 1:
        problems.append("need >=3 filter questions with >=1 in test")
    if not checks["unique_ids"]:
        problems.append("duplicate question ids")
    _write_json(RESULTS / "benchmark_verification.json",
                {"timestamp": _now(), "checks": checks, "evidence": rows, "problems": problems})
    print(json.dumps(checks))
    print("Evidence found on gold page:", sum(r["found"] for r in rows), "/", len(rows))
    for p in problems:
        print("PROBLEM:", p)
    return not problems


# --------------------------------------------------------------------------- evaluate
def cmd_evaluate() -> None:
    questions = json.loads(BENCHMARK.read_text(encoding="utf-8"))["questions"]
    embedder = _embedder()
    store = _store(embedder)
    for index in INDEXES:
        if store.count(index) == 0:
            sys.exit(f"Index {index} is empty - run `python -m src.run ingest` first.")
    t0 = time.perf_counter()
    qvecs = {q["id"]: embedder.embed_query(q["question"]) for q in questions}
    query_embed_seconds = time.perf_counter() - t0

    all_traces: list[dict[str, Any]] = []
    timing: dict[str, float] = {}
    for name, cfg in STRATEGIES.items():
        traces = []
        ts = time.perf_counter()
        for q in questions:
            filters = q.get("filter") if cfg["use_filter"] else None
            hits = store.search(cfg["index"], qvecs[q["id"]], TOP_K, filters)
            trace = evaluate_query(q, hits)
            trace.update({"strategy": name, "index": cfg["index"], "applied_filter": filters})
            traces.append(trace)
        timing[name] = round(time.perf_counter() - ts, 3)
        path = RESULTS / "traces" / f"strategy_{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for t in traces:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        all_traces.extend(traces)

    summary = summarize(all_traces)
    ingest = json.loads((RESULTS / "ingest_report.json").read_text(encoding="utf-8"))
    first_run = ingest["runs"][0]["indexes"]
    metrics = {
        "timestamp": _now(), "top_k": TOP_K, "embedding_model": embedder.model_name,
        "strategies": STRATEGIES, "indexes": INDEXES, "selection_rule": SELECTION_RULE,
        "query_embedding_seconds_all_questions": round(query_embed_seconds, 3),
        "search_seconds_per_strategy_all_questions": timing,
        "summary": summary,
        "chunk_counts": {s: first_run[STRATEGIES[s]["index"]]["chunks"] for s in STRATEGIES},
        "cost_usd": 0.0,
    }
    _write_json(RESULTS / "metrics.json", metrics)
    _write_metrics_md(metrics, ingest)
    _write_experiment_log(summary)
    _write_question_table(all_traces)
    for name in STRATEGIES:
        for split in ("dev", "test"):
            s = summary[name][split]
            print(f"{name} {split}: Hit@1 {s['hit_at_1']}/{s['N']}  Hit@3 {s['hit_at_3']}/{s['N']}  "
                  f"filter-compliant {s['filter_compliant_top3']}/{s['filter_questions']}")


def _write_metrics_md(metrics: dict[str, Any], ingest: dict[str, Any]) -> None:
    first = ingest["runs"][0]["indexes"]
    lines = ["# Retrieval metrics (auto-generated by `python -m src.run evaluate`)", "",
             f"Run: {metrics['timestamp']} - model `{metrics['embedding_model']}` - top-{metrics['top_k']} - cost $0", "",
             "| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Filter compliant (n/N) | Chunks | Embed+store time (s, first ingest) |",
             "|---|---|---|---|---|---|---|"]
    for name, cfg in metrics["strategies"].items():
        for split in ("dev", "test"):
            s = metrics["summary"][name][split]
            fc = f"{s['filter_compliant_top3']}/{s['filter_questions']}" if s["filter_questions"] else "N/A"
            idx = first[cfg["index"]]
            lines.append(f"| {name} | {split} | {s['hit_at_1']}/{s['N']} | {s['hit_at_3']}/{s['N']} | {fc} | "
                         f"{idx['chunks']} | {idx['embed_and_store_seconds']} |")
    lines += ["", f"Selection rule: {metrics['selection_rule']}", "",
              "Filter-compliance is only meaningful for C: A and B never receive a filter, "
              "so their column shows whether unfiltered top-3 happened to stay inside the requested scope."]
    (RESULTS / "metrics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_experiment_log(summary: dict[str, Any]) -> None:
    hypotheses = {
        "A": "Baseline: fixed windows may cut sentences and split evidence across chunks",
        "B": "Paragraph-aware chunks keep claims and their numbers together -> higher Evidence Hit@3 and coherence than A",
        "C": "Both editions report the same indicators with different values; filtering by edition removes wrong-edition hits on filter questions",
    }
    rows = []
    for name, cfg in STRATEGIES.items():
        idx = INDEXES[cfg["index"]]
        d, t = summary[name]["dev"], summary[name]["test"]
        rows.append({
            "strategy": name, "chunking": idx["chunking"],
            "chunk_size": idx.get("size", idx.get("max_size")), "overlap": idx.get("overlap", 0),
            "metadata": "document_id;source;page;edition;year;section;section_title;language;char_start;char_end",
            "filter": "edition/section when question supplies it" if cfg["use_filter"] else "none",
            "vectorizer": EMBEDDING_MODEL, "hypothesis": hypotheses[name],
            "dev_hit1": f"{d['hit_at_1']}/{d['N']}", "dev_hit3": f"{d['hit_at_3']}/{d['N']}",
            "test_hit1": f"{t['hit_at_1']}/{t['N']}", "test_hit3": f"{t['hit_at_3']}/{t['N']}",
            "notes": f"index {cfg['index']}; Chroma cosine; top-{TOP_K}",
        })
    _write_csv(ROOT / "artifacts" / "experiment_log.csv", rows)


def _write_question_table(traces: list[dict[str, Any]]) -> None:
    rows = []
    for t in traces:
        rows.append({
            "strategy": t["strategy"], "question_id": t["question_id"], "split": t["split"], "type": t["type"],
            "filter": json.dumps(t["filter"]) if t["filter"] else "",
            "hit_at_1": int(t["hit_at_1"]), "hit_at_3": int(t["hit_at_3"]),
            "gold_page_in_top3": int(t["gold_page_in_top3"]),
            "top3": " | ".join(f"{h['chunk_id']} ({h['score']:.3f})" for h in t["hits"]),
        })
    _write_csv(RESULTS / "per_question.csv", rows)


# --------------------------------------------------------------------------- audit sheets
def cmd_audit() -> None:
    pages, _, _, manifest = load_pages()
    sections = {s["source_id"]: s["sections"] for s in manifest["sources"]}
    page_flat = {(p.document_id, p.page): flatten(p.text) for p in pages}
    chunks = {i: build_chunks(pages, i) for i in INDEXES}

    # Coherence: 10 positions fixed before scoring - every 10th content page in (document_id, page)
    # order, at the character offset in the middle of the page's normalized text.
    ordered = sorted(pages, key=lambda p: (p.document_id, p.page))
    rows = []
    for n, page in enumerate(ordered[::10][:10], start=1):
        text, _ = page_text(page)
        offset = len(text) // 2
        for name, cfg in STRATEGIES.items():
            if name == "C":
                continue  # C uses exactly B's chunks; coherence of C == B
            cands = [c for c in chunks[cfg["index"]] if c.document_id == page.document_id and c.page == page.page
                     and c.metadata["char_start"] <= offset < c.metadata["char_end"]]
            c = cands[0]
            rows.append({"position_id": f"pos{n:02d}", "document_id": page.document_id, "page": page.page,
                         "char_offset": offset, "strategy": name, "chunk_id": c.chunk_id,
                         "chunk_chars": len(c.text), "chunk_text": c.text,
                         "label_0_2": "", "reason": "", "labeller": ""})
    _write_audit(RESULTS / "audit_coherence.csv", rows)

    # Metadata + grounding: 5 test questions x top-3 per strategy, from the saved traces.
    meta_rows, ground_rows = [], []
    for name in STRATEGIES:
        for line in (RESULTS / "traces" / f"strategy_{name}.jsonl").read_text(encoding="utf-8").splitlines():
            t = json.loads(line)
            if t["split"] != "test":
                continue
            for h in t["hits"]:
                m = h["metadata"]
                sec = section_for(int(m["page"]), sections[m["document_id"]])
                meta_rows.append({
                    "strategy": name, "question_id": t["question_id"], "rank": h["rank"], "chunk_id": h["chunk_id"],
                    "source": m["source"], "page": m["page"], "edition": m["edition"], "section": m["section"],
                    "auto_text_on_stated_page": flatten(h["text"]) in page_flat.get((m["document_id"], int(m["page"])), ""),
                    "auto_section_matches_toc": bool(sec) and sec["section"] == m["section"],
                    "required_filter": json.dumps(t["filter"]) if t["filter"] else "",
                    "respects_filter": h["respects_filter"] if t["filter"] else "",
                    "metadata_complete_and_correct": "", "notes": "", "labeller": "",
                })
            ground_rows.append({
                "strategy": name, "question_id": t["question_id"], "question": t["question"],
                "filter": json.dumps(t["filter"]) if t["filter"] else "",
                "expected_answer": t["expected_answer"], "auto_evidence_hit_at_3": int(t["hit_at_3"]),
                **{f"top{h['rank']}": f"[{h['chunk_id']}] {h['text']}" for h in t["hits"]},
                "label_0_2": "", "reason": "", "labeller": "",
            })
    _write_audit(RESULTS / "audit_metadata.csv", meta_rows)
    _write_audit(RESULTS / "audit_grounding.csv", ground_rows)
    print(f"Wrote audit sheets: coherence={len(rows)} rows, metadata={len(meta_rows)} rows, grounding={len(ground_rows)} rows")


def cmd_summarize_audit() -> None:
    """Aggregate the (manually labelled) audit sheets; refuses to run on unlabelled sheets."""
    def read(name: str) -> list[dict[str, str]]:
        with (RESULTS / name).open(encoding="utf-8") as f:
            return list(csv.DictReader(f))

    coh, meta, ground = read("audit_coherence.csv"), read("audit_metadata.csv"), read("audit_grounding.csv")
    for name, rows, col in (("coherence", coh, "label_0_2"), ("metadata", meta, "metadata_complete_and_correct"),
                            ("grounding", ground, "label_0_2")):
        if any(not r[col].strip() for r in rows):
            sys.exit(f"{name} sheet has unlabelled rows - label them first.")
    out: dict[str, Any] = {"timestamp": _now(), "labeller": sorted({r["labeller"] for r in coh + meta + ground}),
                           "strategies": {}}
    for name, cfg in STRATEGIES.items():
        c_rows = [r for r in coh if r["strategy"] == ("B" if name == "C" else name)]
        c = [int(r["label_0_2"]) for r in c_rows]
        m_rows = [r for r in meta if r["strategy"] == name]
        f_q = sorted({r["question_id"] for r in m_rows if r["required_filter"]})
        f_ok = sum(all(r["respects_filter"] == "True" for r in m_rows if r["question_id"] == q) for q in f_q)
        g = [int(r["label_0_2"]) for r in ground if r["strategy"] == name]
        out["strategies"][name] = {
            "coherence_mean_of_2": round(statistics.fmean(c), 2), "coherence_n": len(c),
            "coherence_note": "C reuses B's chunks" if name == "C" else "",
            "metadata_correct": f"{sum(r['metadata_complete_and_correct'] == '1' for r in m_rows)}/{len(m_rows)}",
            "filter_compliant_test": f"{f_ok}/{len(f_q)}" if f_q else "N/A",
            "grounding_counts": {str(k): g.count(k) for k in (0, 1, 2)},
            "grounding_mean_of_2": round(statistics.fmean(g), 2), "grounding_n": len(g),
        }
    _write_json(RESULTS / "audit_summary.json", out)
    lines = ["# Audit summary (auto-aggregated from results/audit_*.csv)", "",
             "Coherence and grounding: AI-drafted labels reviewed by the student. "
             "Metadata: automated checks (fields present, chunk text on stated page, section matches TOC) plus a manual "
             "row-by-row comparison with the PDF page text; see the labeller column for review status.", "",
             f"Labeller: {', '.join(out['labeller'])}", "",
             "| Strategy | Coherence mean /2 (n) | Metadata complete & correct (n/N) | Filter compliant, test (n/N) | Grounding 0/1/2 | Grounding mean /2 |",
             "|---|---|---|---|---|---|"]
    for name, s in out["strategies"].items():
        gc = s["grounding_counts"]
        note = " (= B chunks)" if name == "C" else ""
        lines.append(f"| {name} | {s['coherence_mean_of_2']} ({s['coherence_n']}){note} | {s['metadata_correct']} | "
                     f"{s['filter_compliant_test']} | {gc['0']}/{gc['1']}/{gc['2']} | {s['grounding_mean_of_2']} |")
    (RESULTS / "audit_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Day 06 data-ingestion pipeline")
    parser.add_argument("stage", choices=["ingest", "verify", "evaluate", "audit", "summarize-audit", "all"])
    stage = parser.parse_args().stage
    if stage in ("ingest", "all"):
        cmd_ingest()
    if stage in ("verify", "all"):
        if not cmd_verify():
            sys.exit("Benchmark verification failed - fix gold evidence before evaluating.")
    if stage in ("evaluate", "all"):
        cmd_evaluate()
    if stage in ("audit", "all"):
        cmd_audit()
    if stage == "summarize-audit":
        cmd_summarize_audit()


if __name__ == "__main__":
    main()
