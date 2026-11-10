"""
Run the examples, sanity-check their results and build the demo website.

    uv run ci/examples.py run     # run every example in order, check its outputs exist
    uv run ci/examples.py check   # sanity checks on the results
    uv run ci/examples.py site    # build the demo website in _site/

Each example runs with its own directory as working directory, as the scripts use relative paths.
"""

import argparse
import ast
import html
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "_site"


@dataclass
class Example:
    script: str  # Path of the script, relative to the repository root
    title: str
    outputs: list[str]  # Files the script must produce, relative to its directory
    published: list[str] = field(default_factory=list)  # Outputs copied to the website

    @property
    def path(self) -> Path:
        return ROOT / self.script

    @property
    def directory(self) -> Path:
        return self.path.parent

    @property
    def slug(self) -> str:
        return self.path.stem


# In run order: the routing examples read the output of the cartography one
EXAMPLES = [
    Example(
        "0_cartography/cartography.py",
        "Cartography of Bologna",
        ["output/map.html", "output/edges.geojson", "output/nodes.geojson"],
        ["output/map.html"],
    ),
    Example(
        "1_routing/forbidden_turns.py",
        "Forbidden turns",
        ["output/forbidden_turns.html"],
        ["output/forbidden_turns.html"],
    ),
    Example(
        "1_routing/path_randomness.py",
        "Path randomness",
        [
            "output/path_randomness.html",
            "output/path_randomness.pdf",
            "output/path_randomness.png",
        ],
        [
            "output/path_randomness.html",
            "output/path_randomness.png",
            "output/path_randomness.pdf",
        ],
    ),
    Example(
        "studies/via_stalingrado_bologna/via_stalingrado_bologna.py",
        "Via Stalingrado, Bologna",
        [
            "output/output_flow.csv",
            "output/flow_comparison.pdf",
            "output/flow_comparison.png",
        ],
        [
            "output/flow_comparison.png",
            "output/flow_comparison.pdf",
            "output/output_flow.csv",
        ],
    ),
]


class CheckError(Exception):
    pass


def ensure(condition: bool, message: str):
    if not condition:
        raise CheckError(message)


# ----------------------------------------------------------------------------- run


def run(_args):
    for example in EXAMPLES:
        print(f"::group::{example.script}", flush=True)
        start = time.perf_counter()
        subprocess.run(
            [sys.executable, example.path.name], cwd=example.directory, check=True
        )
        elapsed = time.perf_counter() - start
        print("::endgroup::", flush=True)
        for output in example.outputs:
            file = example.directory / output
            ensure(file.is_file(), f"{example.script}: missing output {output}")
            ensure(file.stat().st_size > 0, f"{example.script}: empty output {output}")
        print(f"OK {example.script} ({elapsed:.1f} s)", flush=True)


# --------------------------------------------------------------------------- check


def check_cartography(example: Example):
    import geopandas as gpd

    edges = gpd.read_file(example.directory / "output/edges.geojson")
    nodes = gpd.read_file(example.directory / "output/nodes.geojson")
    ensure(len(edges) > 0, "no edges")
    ensure(len(nodes) > 0, "no nodes")
    for column in ("id", "source", "target", "length", "geometry"):
        ensure(column in edges.columns, f"edges have no '{column}' column")
    ensure(edges["id"].is_unique, "edge ids are not unique")
    ensure(nodes["id"].is_unique, "node ids are not unique")
    unknown = (set(edges["source"]) | set(edges["target"])) - set(nodes["id"])
    ensure(not unknown, f"{len(unknown)} edge endpoints are not in the nodes")
    ensure(bool((edges["length"] > 0).all()), "some edges have a non-positive length")
    return f"{len(edges)} edges, {len(nodes)} nodes"


def count_in_html(example: Example, name: str, needle: str) -> int:
    return (example.directory / "output" / name).read_text().count(needle)


def check_forbidden_turns(example: Example):
    turns = count_in_html(example, "forbidden_turns.html", "L.polyline.antPath(")
    ensure(turns > 0, "the map draws no forbidden turn")
    return f"{turns} forbidden turns drawn"


def check_path_randomness(example: Example):
    routes = count_in_html(example, "path_randomness.html", "L.polyline.antPath(")
    ensure(routes > 0, "the map draws no route")
    return f"{routes} routes drawn"


def check_via_stalingrado(example: Example):
    import polars as pl

    toks = (example.directory / "input/input_flow.txt").read_text().split()
    time_unit, schedule = int(toks[0]), [int(x) for x in toks[1:]]
    scheduled = sum(schedule)

    df = pl.read_csv(example.directory / "output/output_flow.csv", separator=";")
    ensure(
        df.columns == ["time", "input_flow", "output_flow"],
        f"unexpected columns {df.columns}",
    )
    n_rows = math.ceil(time_unit * len(schedule) / 300)
    ensure(len(df) == n_rows, f"{len(df)} rows instead of {n_rows}")
    ensure(
        df["time"].to_list() == list(range(0, 300 * n_rows, 300)),
        "times are not every 300 ticks",
    )
    ensure(df.select(pl.all() >= 0).to_numpy().all(), "negative counts")

    flow_in, flow_out = int(df["input_flow"].sum()), int(df["output_flow"].sum())
    # The vehicles inserted after the last row are not recorded
    ensure(
        0.99 * scheduled <= flow_in <= scheduled,
        f"input flow {flow_in} is not the scheduled {scheduled}",
    )
    ensure(
        abs(flow_out - flow_in) <= 0.05 * flow_in,
        f"output flow {flow_out} is more than 5% away from input flow {flow_in}",
    )
    return f"input flow {flow_in}, output flow {flow_out}"


CHECKS = {
    "cartography": check_cartography,
    "forbidden_turns": check_forbidden_turns,
    "path_randomness": check_path_randomness,
    "via_stalingrado_bologna": check_via_stalingrado,
}


def check(_args):
    failed = False
    for example in EXAMPLES:
        try:
            print(f"OK {example.script}: {CHECKS[example.slug](example)}")
        except Exception as error:
            print(f"FAIL {example.script}: {error!r}")
            failed = True
    if failed:
        sys.exit(1)


# ---------------------------------------------------------------------------- site

STYLE = """
:root {
  --bg: #f7f7f5; --card: #ffffff; --text: #1d1d1b; --muted: #5f5f5a;
  --border: #e2e2dd; --accent: #1a5fb4;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #161615; --card: #20201f; --text: #ececea; --muted: #a3a39e;
    --border: #34342f; --accent: #78aeed;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 960px; margin: 0 auto; padding: 32px 16px 64px; }
header p { color: var(--muted); }
h1 { margin: 0 0 4px; font-size: 1.9rem; }
h2 { margin: 0 0 8px; font-size: 1.25rem; }
section {
  background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 20px; margin-top: 20px;
}
section p { color: var(--muted); margin: 0 0 12px; white-space: pre-line; }
a { color: var(--accent); }
.links { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 0; padding: 0; list-style: none; }
img { display: block; max-width: 100%; height: auto; margin-top: 14px; background: #fff; border-radius: 6px; }
footer { color: var(--muted); font-size: 0.9rem; margin-top: 32px; }
"""


def page(sections: str, repo_url: str, ref: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>dsf examples</title>
<style>{STYLE}</style>
</head>
<body>
<main>
<header>
<h1>dsf examples</h1>
<p>Outputs of the usage examples of the
<a href="https://github.com/physycom/DynamicalSystemFramework">DynamicalSystemFramework</a>,
regenerated by CI on every change.</p>
</header>
{sections}
<footer>Built from <a href="{repo_url}/tree/{ref}">{html.escape(ref[:12])}</a>
on {time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}.</footer>
</main>
</body>
</html>
"""


def site(_args):
    repo_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', 'Grufoony/dsf-examples')}"
    ref = os.environ.get("GITHUB_SHA", "main")

    shutil.rmtree(SITE, ignore_errors=True)
    SITE.mkdir()
    sections = []
    for example in EXAMPLES:
        target = SITE / example.slug
        target.mkdir()
        links, images = [], []
        for output in example.published:
            source = example.directory / output
            ensure(source.is_file(), f"{example.script}: missing output {output}")
            shutil.copy2(source, target / source.name)
            href = f"{example.slug}/{source.name}"
            if source.suffix == ".png":
                images.append(
                    f'<a href="{href}"><img src="{href}" alt="{html.escape(example.title)} figure" loading="lazy"></a>'
                )
            else:
                label = {
                    ".html": "Open the interactive map",
                    ".pdf": "Figure (PDF)",
                    ".csv": "Data (CSV)",
                }[source.suffix]
                links.append(f'<li><a href="{href}">{label}</a></li>')
        links.append(
            f'<li><a href="{repo_url}/blob/{ref}/{example.script}">Source code</a></li>'
        )
        docstring = ast.get_docstring(ast.parse(example.path.read_text())) or ""
        sections.append(
            f"""<section>
<h2>{html.escape(example.title)}</h2>
<p>{html.escape(docstring)}</p>
<ul class="links">{"".join(links)}</ul>
{"".join(images)}
</section>"""
        )
    (SITE / "index.html").write_text(page("\n".join(sections), repo_url, ref))
    (SITE / ".nojekyll").touch()
    print(f"Site built in {SITE}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    commands = parser.add_subparsers(required=True)
    for name, function in (("run", run), ("check", check), ("site", site)):
        commands.add_parser(name).set_defaults(function=function)
    args = parser.parse_args()
    try:
        args.function(args)
    except (CheckError, subprocess.CalledProcessError) as error:
        print(f"FAIL {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
