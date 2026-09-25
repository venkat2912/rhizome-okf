"""Build the paper PDF: fills the recall chart from eval/results.json and renders with WeasyPrint."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

res = json.load(open(os.path.join(ROOT, "eval", "results.json")))
methods = ["random", "same directory + lexical", "Leiden community + lexical", "graph (import distance)",
           "hybrid (graph ⊕ lexical)", "lexical (TF-IDF)", "fusion (RRF lexical+graph)"]
labels = {"random": "Random", "same directory + lexical": "Same directory",
          "Leiden community + lexical": "Leiden community", "graph (import distance)": "Graph (import distance)",
          "hybrid (graph ⊕ lexical)": "Interleaved graph ⊕ lexical", "lexical (TF-IDF)": "Lexical (TF-IDF)",
          "fusion (RRF lexical+graph)": "Fusion (RRF)"}
mean = {m: [sum(e["cochange"]["recall"][m][k] for e in res.values()) / len(res) for k in ("5", "10")]
        for m in methods}

W, row, left, top = 680, 30, 190, 30
H = top + row * len(methods) + 40
scale = (W - left - 60) / 0.8
parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-family="Poppins" font-size="11">']
for t in (0, 0.2, 0.4, 0.6, 0.8):
    x = left + t * scale
    parts.append(f'<line x1="{x:.1f}" y1="{top - 6}" x2="{x:.1f}" y2="{H - 34}" stroke="#e3e6ea"/>')
    parts.append(f'<text x="{x:.1f}" y="{H - 20}" text-anchor="middle" fill="#6b7280" font-size="10">{t:.1f}</text>')
parts.append(f'<text x="{left + 0.4 * scale:.1f}" y="{H - 4}" text-anchor="middle" fill="#374151" font-size="10.5">'
             'Mean recall over five repositories</text>')
for i, m in enumerate(methods):
    y = top + i * row
    r5, r10 = mean[m]
    bold = ' font-weight="600"' if m in ("graph (import distance)", "fusion (RRF lexical+graph)") else ""
    parts.append(f'<text x="{left - 10}" y="{y + 15}" text-anchor="end" fill="#111827"{bold}>{labels[m]}</text>')
    parts.append(f'<rect x="{left}" y="{y + 2}" width="{r10 * scale:.1f}" height="11" fill="#9dbbe3"/>')
    parts.append(f'<rect x="{left}" y="{y + 13}" width="{r5 * scale:.1f}" height="11" fill="#1a5fb4"/>')
    parts.append(f'<text x="{left + r10 * scale + 4:.1f}" y="{y + 11}" fill="#374151" font-size="9.5">{r10:.3f}</text>')
    parts.append(f'<text x="{left + r5 * scale + 4:.1f}" y="{y + 22}" fill="#1a5fb4" font-size="9.5">{r5:.3f}</text>')
lx = W - 150
parts.append(f'<rect x="{lx}" y="4" width="10" height="10" fill="#1a5fb4"/><text x="{lx + 14}" y="13" font-size="10">recall@5</text>')
parts.append(f'<rect x="{lx + 72}" y="4" width="10" height="10" fill="#9dbbe3"/><text x="{lx + 86}" y="13" font-size="10">recall@10</text>')
parts.append("</svg>")
chart = "\n".join(parts)

html = open(os.path.join(HERE, "paper.html"), encoding="utf-8").read().replace("{{FIG_RECALL}}", chart)
open(os.path.join(HERE, "paper.built.html"), "w", encoding="utf-8").write(html)
import weasyprint  # noqa: E402
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "rhizome-paper.pdf")
weasyprint.HTML(os.path.join(HERE, "paper.built.html")).write_pdf(out)
print("wrote", out, {m: [round(v, 3) for v in mean[m]] for m in methods})
