from pathlib import Path

from beast_mcp import create_app

app = create_app(Path(__file__).resolve().parents[1], "college-mcp",
                 instructions="Scarlet College courses and lessons. Call bootstrap_guide first.")
