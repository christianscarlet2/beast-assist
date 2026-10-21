"""RAG over Scarlet College: chunk lessons by heading, embed, store in PostgreSQL with pgvector.

Embeddings: EMBEDDINGS=local (default) runs BAAI/bge-small-en-v1.5 on CPU via fastembed (384 dims);
EMBEDDINGS=bedrock calls Amazon Titan Text Embeddings V2 (512 dims: Titan offers only 256, 512 or 1024).
Each model gets its own tables, so both indexes can live side by side and be compared."""
import json
import os
import re

_local = None

# EMBEDDINGS -> (dimensions, chunks table, index-state table)
SPACES = {
    "local": (384, "college_chunks", "college_index"),
    "bedrock": (512, "college_chunks_titan", "college_index_titan"),
}


def space() -> tuple[int, str, str]:
    mode = os.environ.get("EMBEDDINGS", "local")
    if mode not in SPACES:
        raise ValueError(f"EMBEDDINGS must be one of {sorted(SPACES)}, not {mode!r}")
    return SPACES[mode]


def embed(texts: list[str], kind: str = "passage") -> list[list[float]]:
    mode = os.environ.get("EMBEDDINGS", "local")
    dim = space()[0]
    if mode == "bedrock":
        import boto3
        rt = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        out = []
        for t in texts:
            r = rt.invoke_model(modelId="amazon.titan-embed-text-v2:0",
                                body=json.dumps({"inputText": t[:8000], "dimensions": dim, "normalize": True}))
            out.append(json.loads(r["body"].read())["embedding"])
        return out
    global _local
    if _local is None:
        from fastembed import TextEmbedding
        _local = TextEmbedding("BAAI/bge-small-en-v1.5", cache_dir=os.environ.get("FASTEMBED_CACHE", None))
    gen = _local.query_embed(texts) if kind == "query" else _local.passage_embed(texts)
    return [v.tolist() for v in gen]


def chunk_markdown(md: str, max_chars: int = 1400) -> list[tuple[str, str]]:
    """Split a lesson on ## / ### headings; long sections are cut on paragraph breaks. -> [(heading, text)]"""
    parts, heading, buf = [], "Introduction", []
    for line in md.splitlines():
        m = re.match(r"^#{2,3}\s+(.*)", line)
        if m:
            if buf:
                parts.append((heading, "\n".join(buf).strip()))
            heading, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if buf:
        parts.append((heading, "\n".join(buf).strip()))
    out = []
    for h, text in parts:
        if not text:
            continue
        while len(text) > max_chars:
            cut = text.rfind("\n\n", 0, max_chars)
            cut = cut if cut > max_chars // 3 else max_chars
            out.append((h, text[:cut].strip()))
            text = text[cut:].strip()
        if text:
            out.append((h, text))
    return out


def vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def schema() -> str:
    dim, chunks, index = space()
    return f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS {chunks} (
  id          bigserial PRIMARY KEY,
  lesson_id   text NOT NULL,
  track       text NOT NULL,
  level       int  NOT NULL,
  title       text NOT NULL,
  heading     text NOT NULL,
  body        text NOT NULL,
  embedding   vector({dim}) NOT NULL
);
CREATE INDEX IF NOT EXISTS {chunks}_lesson ON {chunks} (lesson_id);
CREATE INDEX IF NOT EXISTS {chunks}_hnsw ON {chunks} USING hnsw (embedding vector_cosine_ops);
CREATE TABLE IF NOT EXISTS {index} (lesson_id text PRIMARY KEY, sha text NOT NULL);
"""
