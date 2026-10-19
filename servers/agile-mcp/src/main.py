from pathlib import Path

from beast_mcp import create_app

app = create_app(Path(__file__).resolve().parents[1], "agile-mcp",
                 instructions="The Warden agile board. Call bootstrap_guide first.")
