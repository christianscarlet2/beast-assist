"""Draw docs/diagrams/live-{dark,light}.svg: the live deployment, laid out by hand so nothing crosses.

    python docs/diagrams/live_svg.py          (writes both themes next to this file)

The layout is explicit on purpose: an auto-layout tool tangled the edges and implied hops that do not exist.
"""
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1600, 940
THEMES = {
    "dark": dict(bg="#0b0f17", node="#182033", text="#e7ebf3", muted="#97a3b8", edge="#8a97b0", label_bg="#0b0f17",
                 azure="#3b8eea", azure_bg="rgba(59,142,234,0.07)", aws="#ff9900", aws_bg="rgba(255,153,0,0.08)",
                 sor="#7d879c", sor_bg="rgba(125,135,156,0.08)", aca_bg="rgba(59,142,234,0.06)", accent="#e0384f"),
    "light": dict(bg="#ffffff", node="#f3f6fb", text="#1b2130", muted="#5b6478", edge="#5b6478", label_bg="#ffffff",
                  azure="#1f6fd1", azure_bg="rgba(31,111,209,0.05)", aws="#d97f00", aws_bg="rgba(217,127,0,0.07)",
                  sor="#7d879c", sor_bg="rgba(125,135,156,0.06)", aca_bg="rgba(31,111,209,0.05)", accent="#c0273d"),
}

# name: (x, y, w, h, lines, kind)   kind: box | db | pill | job
NODES = {
    "browser": (30, 415, 160, 60, ["Browser"], "pill"),
    "gh": (30, 195, 170, 66, ["GitHub Actions", "tests · image"], "job"),
    "entra": (280, 170, 210, 70, ["Microsoft Entra ID", "tokens · app roles"], "db"),
    "apim": (540, 170, 210, 70, ["API Management", "validate-jwt · skill header"], "box"),
    "demo": (280, 395, 210, 100, ["beast-demo", "cognizant.scarletbeast.com", "console · agent · status"], "box"),
    "agile": (800, 320, 190, 60, ["beast-agile-mcp"], "box"),
    "college": (800, 430, 190, 60, ["beast-college-mcp"], "box"),
    "index": (560, 560, 190, 60, ["beast-index job", "daily RAG ingest"], "job"),
    "opa": (800, 560, 190, 60, ["beast-opa", "internal only"], "box"),
    "registry": (1040, 560, 160, 60, ["beast-registry"], "box"),
    "pg": (1000, 760, 220, 80, ["Azure Database for", "PostgreSQL + pgvector"], "db"),
    "blob": (280, 760, 190, 76, ["Blob Storage", "walkthrough video"], "db"),
    "bedrock": (1300, 160, 240, 72, ["Amazon Bedrock", "Nova Pro · Titan V2"], "box"),
    "board": (1300, 325, 240, 62, ["Agile board API"], "db"),
    "lessons": (1300, 420, 240, 62, ["Scarlet College API"], "db"),
}
GROUPS = [  # x, y, w, h, title, color key
    (240, 120, 1000, 790, "Microsoft Azure", "azure"),
    (255, 290, 970, 355, "Azure Container Apps · Central US", "aca"),
    (1270, 110, 300, 150, "Amazon Web Services · us-east-1", "aws"),
    (1270, 290, 300, 240, "Systems of record · Scarlet Beast server", "sor"),
]
# (path, label, label_xy, dashed)
EDGES = [
    ("M190,445 H276", "HTTPS", (233, 436), False),
    ("M385,395 V244", "client credentials", (385, 362), True),
    ("M490,430 H645 V244", "JWT + X-Skill-Id", (568, 421), False),
    ("M750,205 H772 V350 H796", None, None, False),
    ("M772,350 V460 H796", None, None, False),
    ("M990,350 H1296", "tool calls", (1140, 341), False),
    ("M990,450 H1296", "tool calls", (1140, 441), False),
    ("M895,490 V556", "allowed?", (852, 527), False),
    ("M800,350 H786 V590 H796", None, None, False),
    ("M1040,590 H994", "policy + skills", (1017, 540), False),
    ("M1120,620 V756", "skills", (1146, 690), False),
    ("M990,478 H1236 V800 H1224", "pgvector search", (1120, 494), False),
    ("M655,620 V800 H996", "daily ingest", (770, 790), False),
    ("M490,412 H515 V95 H1258 V196 H1296", "agent model calls (Bedrock Converse)", (900, 86), False),
    ("M280,798 H110 V479", "video", (152, 640), True),
    ("M200,228 H232 V318 H251", "image", (232, 286), False),
]


JOB_DASH = ' stroke-dasharray="6 4"'
EDGE_DASH = ' stroke-dasharray="5 4"'


def node_svg(t, x, y, w, h, lines, kind):
    out = []
    stroke = t["accent"] if kind == "pill" else t["muted"]
    if kind == "db":
        ry = 9
        out.append(f'<path d="M{x},{y + ry} a{w / 2},{ry} 0 0,1 {w},0 v{h - 2 * ry} a{w / 2},{ry} 0 0,1 {-w},0 z" '
                   f'fill="{t["node"]}" stroke="{stroke}" stroke-width="1.5"/>')
        out.append(f'<path d="M{x},{y + ry} a{w / 2},{ry} 0 0,0 {w},0" fill="none" stroke="{stroke}" stroke-width="1.5"/>')
    else:
        r = h / 2 if kind == "pill" else 8
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{t["node"]}" stroke="{stroke}" '
                   f'stroke-width="1.5"{JOB_DASH if kind == "job" else ""}/>')
    n = len(lines)
    cy = y + h / 2 + (5 if kind == "db" else 0)
    for i, ln in enumerate(lines):
        dy = (i - (n - 1) / 2) * 20
        weight, size, fill = ("700", 16, t["text"]) if i == 0 else ("400", 13.5, t["muted"])
        out.append(f'<text x="{x + w / 2}" y="{cy + dy + 5}" text-anchor="middle" font-size="{size}" '
                   f'font-weight="{weight}" fill="{fill}">{escape(ln)}</text>')
    return "\n".join(out)


def render(theme: str) -> str:
    t = THEMES[theme]
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'font-family="Inter, Segoe UI, Helvetica, Arial, sans-serif" role="img" '
         f'aria-label="Beast Assist live deployment on Azure and AWS">',
         f'<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         f'<path d="M0,0 L10,5 L0,10 z" fill="{t["edge"]}"/></marker></defs>',
         f'<rect width="{W}" height="{H}" fill="{t["bg"]}"/>',
         f'<text x="30" y="52" font-size="26" font-weight="700" fill="{t["text"]}">Beast Assist · live deployment</text>',
         f'<text x="30" y="80" font-size="15" fill="{t["muted"]}">Every tool call: Entra ID token → API Management → MCP server → OPA → backend</text>']
    for x, y, w, h, title, key in GROUPS:
        color = t["azure"] if key == "aca" else t[key]
        fill = t["aca_bg"] if key == "aca" else t[f"{key}_bg"]
        dash = ' stroke-dasharray="8 5"' if key in ("sor", "aca") else ""
        s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{color}" stroke-width="1.6"{dash}/>')
        tx, anchor = (x + w - 16, "end") if key == "aca" else (x + 16, "start")  # keep the ACA title clear of edges
        s.append(f'<text x="{tx}" y="{y + 26}" text-anchor="{anchor}" font-size="14.5" font-weight="700" fill="{color}">{escape(title)}</text>')
    for path, label, lxy, dashed in EDGES:
        s.append(f'<path d="{path}" fill="none" stroke="{t["edge"]}" stroke-width="1.6" marker-end="url(#a)"'
                 f'{EDGE_DASH if dashed else ""}/>')
    for name, (x, y, w, h, lines, kind) in NODES.items():
        s.append(node_svg(t, x, y, w, h, lines, kind))
    for path, label, lxy, dashed in EDGES:  # labels last, over everything
        if label:
            lx, ly = lxy
            tw = len(label) * 7.1 + 12
            s.append(f'<rect x="{lx - tw / 2}" y="{ly - 13}" width="{tw}" height="19" rx="4" fill="{t["label_bg"]}" opacity="0.92"/>')
            s.append(f'<text x="{lx}" y="{ly + 1}" text-anchor="middle" font-size="13" fill="{t["muted"]}">{escape(label)}</text>')
    s.append("</svg>")
    return "\n".join(s)


if __name__ == "__main__":
    here = Path(__file__).parent
    for theme in THEMES:
        (here / f"live-{theme}.svg").write_text(render(theme))
        print("wrote", here / f"live-{theme}.svg")
