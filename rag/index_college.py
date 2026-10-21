#!/usr/bin/env python3
"""Step 1-4 of the RAG pipeline: ingest Scarlet College lessons, chunk them, embed the chunks, store
them in PostgreSQL + pgvector. Re-run any time: a lesson's chunks are replaced only when its text changed.

  python rag/index_college.py [--course mcp] [--rebuild]
Env: COLLEGE_BASE, RAG_DSN, EMBEDDINGS=local|bedrock"""
import argparse
import hashlib
import os
import time

import httpx
import psycopg

from beast_rag import chunk_markdown, embed, schema, space, vec

BASE = os.environ.get("COLLEGE_BASE", "https://college.scarletbeast.com").rstrip("/")
DSN = os.environ.get("RAG_DSN", "postgresql://beast:beast@localhost:55432/beast")


def lesson_text(c: dict) -> str:
    """What gets indexed: the body, the practice, and the key terms (so definitions are findable)."""
    terms = "\n".join(f"- **{t.get('term')}**: {t.get('definition', '')}" for t in c.get("key_terms", []))
    return "\n\n".join(x for x in (c.get("body_md", ""), "## Practice\n" + c.get("practice_md", ""),
                                   "## Key terms\n" + terms if terms else "") if x.strip())


def get_json(http: httpx.Client, path: str, tries: int = 4):
    """The site sits behind a busy shared web server: retry dropped connections with backoff."""
    for i in range(tries):
        try:
            r = http.get(path)
            r.raise_for_status()
            return r.json()
        except (httpx.TransportError, httpx.HTTPStatusError):
            if i == tries - 1:
                raise
            time.sleep(2 ** i)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", default="")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    http = httpx.Client(base_url=BASE, timeout=30)
    cat = get_json(http, "/api/catalog")
    lessons = [l for l in cat["lessons"] if not a.course or l["track"] == a.course]
    _, chunks_t, index_t = space()
    with psycopg.connect(DSN, autocommit=True) as con:
        con.execute(schema())
        if a.rebuild:
            con.execute(f"TRUNCATE {chunks_t}, {index_t}")
        done = dict(con.execute(f"SELECT lesson_id, sha FROM {index_t}").fetchall())
        t0, n_chunks, n_new = time.time(), 0, 0
        for l in lessons:
            c = get_json(http, f"/api/lesson/{l['id']}")["lesson"]["content"]
            text = lesson_text(c)
            sha = hashlib.sha256(text.encode()).hexdigest()
            if done.get(l["id"]) == sha:
                continue
            chunks = chunk_markdown(text)
            # the title rides along in every embedded chunk, so a passage keeps its context
            vecs = embed([f"{c['title']} - {h}\n{body}" for h, body in chunks])
            with con.transaction():
                con.execute(f"DELETE FROM {chunks_t} WHERE lesson_id = %s", (l["id"],))
                with con.cursor() as cur:
                    cur.executemany(
                        f"INSERT INTO {chunks_t} (lesson_id, track, level, title, heading, body, embedding) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s::vector)",
                        [(l["id"], l["track"], l["level"], c["title"], h, body, vec(v))
                         for (h, body), v in zip(chunks, vecs)])
                con.execute(f"INSERT INTO {index_t} VALUES (%s,%s) ON CONFLICT (lesson_id) DO UPDATE SET sha=EXCLUDED.sha",
                            (l["id"], sha))
            n_chunks += len(chunks)
            n_new += 1
            print(f"  {l['track']:<12} L{l['level']:<2} {len(chunks):>3} chunks  {c['title'][:70]}")
        total = con.execute(f"SELECT count(*) FROM {chunks_t}").fetchone()[0]
    print(f"indexed {n_new} lessons ({n_chunks} chunks) in {time.time() - t0:.0f}s; {total} chunks in {chunks_t}")


if __name__ == "__main__":
    main()
