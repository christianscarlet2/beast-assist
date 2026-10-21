"""The coordinator's answer is plain text whatever block shape the model returns."""
from agent.coordinator import text_of


def test_text_of_keeps_only_text_blocks():
    nova = [{"type": "reasoning_content", "reasoning_content": {"text": "thinking"}},
            {"type": "text", "text": "\n\nIn progress: BA-7"}]
    assert text_of(nova) == "In progress: BA-7"
    assert text_of("plain") == "plain"
