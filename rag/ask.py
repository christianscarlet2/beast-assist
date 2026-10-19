#!/usr/bin/env python3
"""Step 5-6 of the RAG pipeline: retrieve the best passages for a question, then generate an answer
grounded in them.

  python rag/ask.py "how do I validate an Entra JWT in FastAPI?" [--course mcp] [--k 5]
With AWS credentials and BEDROCK_MODEL_ID set, a Bedrock model writes the answer from the passages;
without them the script prints the retrieved context, which is the half of RAG you can check by eye."""
import argparse
import os

import psycopg

from beast_rag import embed, vec

DSN = os.environ.get("RAG_DSN", "postgresql://beast:beast@localhost:55432/beast")
PROMPT = """Answer the question using ONLY the numbered passages. Cite passages like [2]. If they do not
contain the answer, say so.

{context}

Question: {question}"""


def retrieve(question: str, k: int = 5, course: str = "") -> list[dict]:
    qv = vec(embed([question], "query")[0])
    sql = ("SELECT lesson_id, track, level, title, heading, body, 1 - (embedding <=> %s::vector) AS score "
           "FROM college_chunks " + ("WHERE track = %s " if course else "") + "ORDER BY embedding <=> %s::vector LIMIT %s")
    args = (qv, course, qv, k) if course else (qv, qv, k)
    with psycopg.connect(DSN) as con:
        cur = con.execute(sql, args)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def generate(question: str, hits: list[dict]) -> str | None:
    model = os.environ.get("BEDROCK_MODEL_ID")
    if not model:
        return None
    import boto3
    context = "\n\n".join(f"[{i}] ({h['title']} / {h['heading']})\n{h['body']}" for i, h in enumerate(hits, 1))
    rt = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    r = rt.converse(modelId=model, messages=[{"role": "user", "content": [
        {"text": PROMPT.format(context=context, question=question)}]}], inferenceConfig={"maxTokens": 700})
    return r["output"]["message"]["content"][0]["text"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--course", default="")
    ap.add_argument("--k", type=int, default=5)
    a = ap.parse_args()
    hits = retrieve(a.question, a.k, a.course)
    for i, h in enumerate(hits, 1):
        print(f"[{i}] {h['score']:.3f}  {h['track']} L{h['level']}  {h['title']} / {h['heading']}")
        print("     " + h["body"][:220].replace("\n", " ") + "…")
    answer = generate(a.question, hits)
    print("\n" + (answer or "(no BEDROCK_MODEL_ID: retrieval only. Set it and AWS credentials to generate an answer.)"))


if __name__ == "__main__":
    main()
