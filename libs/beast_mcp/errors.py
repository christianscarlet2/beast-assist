class ToolFailure(Exception):
    """A failure the agent can act on. `hint` says what to do next; it reaches the model verbatim."""

    def __init__(self, message: str, hint: str = "", code: str = "tool_failed"):
        super().__init__(message)
        self.message, self.hint, self.code = message, hint, code

    def text(self) -> str:
        return f"{self.code}: {self.message}" + (f" Next: {self.hint}" if self.hint else "")
