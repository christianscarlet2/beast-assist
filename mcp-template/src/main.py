from pathlib import Path

from beast_mcp import create_app

app = create_app(Path(__file__).resolve().parents[1], "template-mcp", instructions="Call bootstrap_guide first.")
