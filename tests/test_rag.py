import pytest
from beast_rag import chunk_markdown, vec


def test_chunks_follow_headings_and_respect_size():
    md = "Intro line\n\n## Alpha\n" + ("word " * 50 + "\n\n") * 10 + "## Beta\nshort"
    chunks = chunk_markdown(md, max_chars=600)
    heads = [h for h, _ in chunks]
    assert heads[0] == "Introduction" and "Alpha" in heads and heads[-1] == "Beta"
    assert all(len(t) <= 600 for _, t in chunks)


def test_vec_literal():
    assert vec([0.5, -1]) == "[0.500000,-1.000000]"


def test_each_embedding_model_has_its_own_tables(monkeypatch):
    from beast_rag import schema, space
    monkeypatch.setenv("EMBEDDINGS", "local")
    assert space() == (384, "college_chunks", "college_index")
    assert "vector(384)" in schema()
    monkeypatch.setenv("EMBEDDINGS", "bedrock")
    dim, chunks, _ = space()
    assert dim in (256, 512, 1024)  # the only sizes Titan V2 offers
    assert chunks != "college_chunks" and f"vector({dim})" in schema()
    monkeypatch.setenv("EMBEDDINGS", "nope")
    with pytest.raises(ValueError):
        space()
