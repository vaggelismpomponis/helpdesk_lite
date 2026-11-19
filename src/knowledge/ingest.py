"""Policy ingestion: parse front matter, chunk, embed, store in pgvector.

Run: python -m src.knowledge.ingest   (idempotent: re-ingesting a version replaces its chunks)
"""
import re
from datetime import date
from pathlib import Path

from .common import DIM, embed, pg, vec

POLICIES = Path(__file__).resolve().parents[1] / "data" / "policies"

DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS policy_chunks (
    doc_id         text NOT NULL,
    effective_date date NOT NULL,
    chunk_index    int  NOT NULL,
    title          text NOT NULL,
    source         text NOT NULL,
    content        text NOT NULL,
    embedding      vector({DIM}) NOT NULL,
    PRIMARY KEY (doc_id, effective_date, chunk_index)
);
"""


def parse(path: Path) -> tuple[dict[str, str], str]:
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n(.*)", path.read_text(encoding="utf-8"), re.S)
    if not m:
        raise ValueError(f"{path.name}: missing front matter")
    lines = (line.split(":", 1) for line in m[1].splitlines() if ":" in line)
    meta = {k.strip(): v.strip().strip('"') for k, v in lines}
    for key in ("doc_id", "title", "effective_date"):
        if key not in meta:
            raise ValueError(f"{path.name}: missing '{key}'")
    date.fromisoformat(meta["effective_date"])
    return meta, m[2].strip()


def chunk(body: str, max_chars: int = 800) -> list[str]:
    """Pack paragraphs into chunks of at most max_chars (a single longer paragraph stays whole)."""
    chunks: list[str] = []
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para:
            continue
        if chunks and len(chunks[-1]) + len(para) < max_chars:
            chunks[-1] += "\n\n" + para
        else:
            chunks.append(para)
    return chunks


def ingest() -> int:
    docs = [(p, *parse(p)) for p in sorted(POLICIES.glob("*.md"))]
    with pg() as conn:  # one transaction: all or nothing
        conn.execute(DDL)
        for path, meta, body in docs:
            parts = chunk(body)
            vectors = embed([f"{meta['title']}\n{c}" for c in parts])
            conn.execute(
                "DELETE FROM policy_chunks WHERE doc_id = %s AND effective_date = %s",
                (meta["doc_id"], meta["effective_date"]),
            )
            for i, (c, v) in enumerate(zip(parts, vectors)):
                conn.execute(
                    "INSERT INTO policy_chunks (doc_id, effective_date, chunk_index, title, source, content, embedding) VALUES (%s,%s,%s,%s,%s,%s,%s::vector)",
                    (meta["doc_id"], meta["effective_date"], i, meta["title"], path.name, c, vec(v)),
                )
    return len(docs)


if __name__ == "__main__":
    print(f"ingested {ingest()} policy files")
