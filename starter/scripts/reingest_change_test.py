"""Re-ingest test on a throw-away Chroma folder (does not touch starter/chroma_db).

1. ingest 3 pages            -> N chunks stored
2. ingest the same 3 pages   -> 0 re-embedded, still N (no duplicates)
3. simulate a changed source: page 2's text is edited and page 3 is removed from the document
   -> only changed chunks are re-embedded, obsolete chunks are deleted, store matches the new version.
Run from starter/:  python scripts/reingest_change_test.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.chunking import by_paragraph  # noqa: E402
from src.embeddings import SentenceTransformerEmbedder  # noqa: E402
from src.run import EMBEDDING_MODEL, RESULTS, load_pages  # noqa: E402
from src.store import ChromaStore  # noqa: E402


def sync(store, embedder, pages):
    chunks = [c for p in pages for c in by_paragraph(p, 600, strategy="T")]
    existing = store.existing("T", "ts-2017-12")
    todo = [c for c in chunks if existing.get(c.chunk_id) != c.metadata["content_hash"]]
    stale = sorted(set(existing) - {c.chunk_id for c in chunks})
    if todo:
        store.upsert("T", todo, embedder.embed_documents([c.text for c in todo]))
    store.delete("T", stale)
    return {"chunks_in_version": len(chunks), "embedded": len(todo), "deleted_stale": len(stale),
            "count_in_store": store.count("T")}


def main():
    pages = [p for p in load_pages()[0] if p.document_id == "ts-2017-12"][:3]
    embedder = SentenceTransformerEmbedder(EMBEDDING_MODEL)
    # Chroma keeps index files open on Windows, so temp-folder cleanup errors are ignored.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = ChromaStore(Path(tmp), embedder.dimensions, embedder.model_name)
        r1 = sync(store, embedder, pages)
        r2 = sync(store, embedder, pages)
        changed = [pages[0], type(pages[1])(**{**pages[1].__dict__, "text": pages[1].text + "\nAdded sentence in a new version."})]
        r3 = sync(store, embedder, changed)
        del store
    result = {"pages": [p.page for p in pages], "first_ingest": r1, "same_version_again": r2,
              "changed_version (p2 edited, p3 removed)": r3,
              "pass": r2["embedded"] == 0 and r2["count_in_store"] == r1["count_in_store"]
                      and r3["count_in_store"] == r3["chunks_in_version"] and r3["deleted_stale"] > 0}
    (RESULTS / "reingest_test.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["pass"]:
        sys.exit("re-ingest test FAILED")


if __name__ == "__main__":
    main()
