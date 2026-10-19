"""The chat model behind the agent.

Production: Amazon Bedrock through the Converse API (ChatBedrockConverse), model BEDROCK_MODEL_ID.
Tests and evals: ScriptedModel replays a fixed list of steps, so the graph, the tool scoping and the
MCP plumbing are tested without a model, deterministically."""
import os
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def bedrock_model():
    from langchain_aws import ChatBedrockConverse
    model = os.environ.get("BEDROCK_MODEL_ID")
    if not model:
        raise RuntimeError("set BEDROCK_MODEL_ID (a model enabled in your Bedrock account) and AWS credentials")
    return ChatBedrockConverse(model=model, region_name=os.environ.get("AWS_REGION", "us-east-1"),
                               temperature=0, max_tokens=1500)


class ScriptedModel(BaseChatModel):
    """Each call returns the next scripted step: {"tool": name, "args": {...}} or {"say": text}."""

    steps: list[dict]
    cursor: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kw):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kw) -> ChatResult:
        step = self.steps[min(self.cursor, len(self.steps) - 1)]
        self.cursor += 1
        if "tool" in step:
            msg = AIMessage(content="", tool_calls=[{"name": step["tool"], "args": step.get("args", {}),
                                                     "id": f"call_{self.cursor}"}])
        else:
            msg = AIMessage(content=step.get("say", "done"))
        return ChatResult(generations=[ChatGeneration(message=msg)])
