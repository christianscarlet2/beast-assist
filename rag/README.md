# RAG over Scarlet College

Retrieval-augmented generation: instead of letting a model answer from memory, find the passages that
answer the question in your own documents, and make the model answer only from those. Here the
documents are every lesson Scarlet College has written.

```
 college.scarletbeast.com/api/catalog          1 INGEST    every ready lesson: body, practice, key terms
        │
        ▼
 beast_rag.chunk_markdown()                    2 CHUNK     split on ## / ### headings, max ~1,400 chars,
        │                                                  long sections cut on paragraph breaks
        ▼
 beast_rag.embed()                             3 EMBED     384-dim vectors: bge-small (local CPU) or
        │                                                  Amazon Titan V2 (EMBEDDINGS=bedrock)
        ▼
 PostgreSQL + pgvector  college_chunks         4 STORE     HNSW index, cosine distance
        │
        ▼
 SELECT … ORDER BY embedding <=> query         5 RETRIEVE  top-k passages for the question's vector
        │
        ▼
 Bedrock Converse, "answer ONLY from [1]..[k]" 6 GENERATE  grounded answer with citations
```

## Run it

```bash
make up                      # PostgreSQL with pgvector is part of the stack (port 55432)
python rag/index_college.py  # steps 1-4; re-run any time, unchanged lessons are skipped
python rag/ask.py "How do I override a FastAPI dependency in a test?"     # steps 5-6
python rag/eval_retrieval.py # how good is retrieval? hit@1, hit@5, MRR over rag/questions.yaml
```

Without `BEDROCK_MODEL_ID`, `ask.py` stops after retrieval and prints the passages. That is the part
of RAG to get right first: if the right passage is not retrieved, no model can answer from it.

## The same RAG inside the agent platform

`college-mcp:search_lessons` runs step 5 as an MCP tool, and the `college-tutor` skill runs step 6:
its workflow tells the agent to search, open the best lessons, answer from them only, and cite them.
The `study-plan-from-job` skill uses the same search to attach a lesson to each skill gap.

## Things to try (each is a one-line change, measured with eval_retrieval.py)

| Experiment | Where | What to watch |
| --- | --- | --- |
| Smaller or larger chunks | `chunk_markdown(max_chars=...)` in `rag/index_college.py` | hit@1 vs hit@5 |
| Drop the title prefix on each chunk | the `embed([f"{c['title']} - {h}..."])` line | hit@1 falls: chunks lose context |
| Titan instead of bge-small | `EMBEDDINGS=bedrock`, then `index_college.py --rebuild` | MRR, cost per 1k chunks |
| More results | `--k 10` | hit@k rises, answer prompts get longer |
| Hybrid search | add a `tsvector` column and blend `ts_rank` with vector score | exact terms like "422" |
| A re-ranker | re-score the top 20 with a cross-encoder, keep 5 | hit@1 |
| Add your own documents | write an ingest step for another source into `college_chunks` (or a new table) | — |
