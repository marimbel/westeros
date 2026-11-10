#!/usr/bin/env python3
"""Build the GitHub Pages site into docs/:

  docs/index.html   live pixel-art world: the real engine runs in the browser via Pyodide
                    (falls back to an embedded recorded chronicle if Pyodide can't load)
  docs/replay.html  analysis replay (charts, relations heatmap, metrics)

  python build_site.py [--seed 8]
"""
import argparse
import glob
import json
import os

from westeros.live import record
from westeros.world import FACTIONS, adjacency
from run import run_one, write_replay

HERE = os.path.dirname(os.path.abspath(__file__))


def build(seed=8):
    os.makedirs(os.path.join(HERE, "docs"), exist_ok=True)
    sources = {}
    for path in sorted(glob.glob(os.path.join(HERE, "westeros", "**", "*.py"), recursive=True)):
        rel = os.path.relpath(path, HERE).replace(os.sep, "/")
        if rel.endswith("agents/llm.py"):
            continue  # the browser world runs heuristic agents only
        with open(path) as fh:
            sources[rel] = fh.read()
    factions = {f: dict(name=d["name"], motto=d["motto"], color=d["color"], kind=d["kind"]) for f, d in FACTIONS.items()}
    frames = record(seed)
    with open(os.path.join(HERE, "viewer", "world_template.html")) as fh:
        html = fh.read()
    for key, val in (("PY", sources), ("REC", frames), ("ADJ", adjacency()), ("FACTIONS", factions)):
        html = html.replace(f"/*__{key}__*/null", json.dumps(val, separators=(",", ":")).replace("</", "<\\/"))
    with open(os.path.join(HERE, "docs", "index.html"), "w") as fh:
        fh.write(html)
    env, summ, thoughts = run_one(seed)
    write_replay(env, summ, thoughts, os.path.join(HERE, "docs", "replay.html"))
    print(f"docs/index.html ({os.path.getsize(os.path.join(HERE, 'docs', 'index.html')) // 1024} KB), docs/replay.html")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=8)
    build(ap.parse_args().seed)
