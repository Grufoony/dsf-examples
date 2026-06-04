"""
Script to generate cartography for a given city.
It uses the `dsf` library to fetch the cartography data and then saves it as a folium map and GeoJSON files for edges and nodes.

The script takes a city name as input (default is "Bologna, Italy") and outputs the cartography data to the `output` directory.
"""

import argparse
from pathlib import Path

from dsf import cartography, logging

OUTPUT_DIR = Path("output")


def main(city: str):
    logging.info(f"Generating cartography for {city}...")
    G, edges, nodes = cartography.get_cartography(city, scc=True)

    map = cartography.to_folium_map(G)

    map.save(OUTPUT_DIR / "map.html")
    logging.info(f"Map saved to {OUTPUT_DIR / 'map.html'}")

    edges.to_file(OUTPUT_DIR / "edges.geojson", driver="GeoJSON")
    logging.info(f"Edges saved to {OUTPUT_DIR / 'edges.geojson'}")
    nodes.to_file(OUTPUT_DIR / "nodes.geojson", driver="GeoJSON")
    logging.info(f"Nodes saved to {OUTPUT_DIR / 'nodes.geojson'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate cartography for a given city."
    )
    parser.add_argument(
        "--city",
        help="The city for which to generate cartography.",
        type=str,
        default="Bologna, Italy",
    )
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(exist_ok=True)
    main(args.city)
