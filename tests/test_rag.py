from beast_rag import chunk_markdown, vec


def test_chunks_follow_headings_and_respect_size():
    md = "Intro line\n\n## Alpha\n" + ("word " * 50 + "\n\n") * 10 + "## Beta\nshort"
    chunks = chunk_markdown(md, max_chars=600)
    heads = [h for h, _ in chunks]
    assert heads[0] == "Introduction" and "Alpha" in heads and heads[-1] == "Beta"
    assert all(len(t) <= 600 for _, t in chunks)


def test_vec_literal():
    assert vec([0.5, -1]) == "[0.500000,-1.000000]"
