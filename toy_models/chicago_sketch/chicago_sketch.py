"""
Script to simulate the Chicago sketch benchmark network using the DSF library.
The script converts the TNTP files of the TransportationNetworks repository into DSF inputs,
runs a traffic simulation fed only by the origin-destination matrix, with agents routed on the
current travel times, and compares the simulated link flows with the user-equilibrium ones.

Nothing is calibrated: the goal is to see how close the flows get with just ODs and travel times.
The benchmark equilibrium uses a generalized cost that adds 0.04 minutes per mile to the travel
times, while DSF routes on travel times only.
"""

from pathlib import Path
import sys

from dsf import logging

# The helpers shared by the toy models live in the parent folder
sys.path.append(str(Path(__file__).resolve().parent.parent))
import utils

HERE = Path(__file__).resolve().parent
INPUT_DIR = HERE / "../TransportationNetworks/Chicago-Sketch"
OUTPUT_DIR = HERE / "output"
NAME = "chicago_sketch"
TITLE = "Chicago sketch"

LENGTH_UNIT = utils.MILE
# Node coordinates are in the Illinois State Plane East system (NAD27), in feet
NODES_CRS = "EPSG:26771"
CENTROID_OFFSET = 500.0  # feet
MAP_LINK_OFFSET = 600.0  # Web Mercator meters
# The whole region, and a zoom on central Chicago (longitude, latitude, half width)
MAP_PANELS = [
    ("Chicago region", None),
    ("Central Chicago", (-87.68, 41.87, 25_000)),
]


def main(args):
    links = utils.read_tntp_network(INPUT_DIR / "ChicagoSketch_net.tntp")
    n_zones = utils.read_n_zones(INPUT_DIR / "ChicagoSketch_net.tntp")
    trips = utils.read_tntp_trips(INPUT_DIR / "ChicagoSketch_trips.tntp")
    nodes = utils.read_tntp_nodes(INPUT_DIR / "ChicagoSketch_node.tntp")
    ue_flows = utils.read_tntp_flows(INPUT_DIR / "ChicagoSketch_flow.tntp")
    logging.info(
        f"Loaded {links.height} links, {n_zones} zones and "
        f"{trips['trips'].sum():.0f} trips per hour."
    )

    # The network file marks every node as a through node, but the benchmark equilibrium
    # routes no traffic through the zones: paths may not cross them
    utils.build_inputs(
        OUTPUT_DIR,
        links,
        trips,
        nodes,
        n_zones,
        length_unit=LENGTH_UNIT,
        centroid_offset=CENTROID_OFFSET,
        crossable_zones=False,
    )
    utils.simulation(
        OUTPUT_DIR,
        NAME,
        trips["trips"].sum(),
        args.insertion_hours,
        args.hours,
        args.threshold,
        args.update_interval,
        args.intelligent_fraction,
        args.seed,
    )
    flows = utils.compare(
        OUTPUT_DIR, NAME, TITLE, links, ue_flows, args.insertion_hours, args.hours
    )
    utils.plot_map(
        OUTPUT_DIR,
        TITLE,
        flows,
        nodes,
        NODES_CRS,
        link_offset=MAP_LINK_OFFSET,
        panels=MAP_PANELS,
    )


if __name__ == "__main__":
    # The network carries the hourly demand in about one hour
    args = utils.parse_args(
        "Compare simulated and user-equilibrium link flows on Chicago sketch.",
        insertion_hours=1.0,
        hours=5,
    )
    OUTPUT_DIR.mkdir(exist_ok=True)
    main(args)
