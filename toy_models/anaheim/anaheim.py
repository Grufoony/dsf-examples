"""
Script to simulate the Anaheim benchmark network using the DSF library.
The script converts the TNTP files of the TransportationNetworks repository into DSF inputs,
runs a traffic simulation fed only by the origin-destination matrix, with agents routed on the
current travel times, and compares the simulated link flows with the user-equilibrium ones.

Nothing is calibrated: the goal is to see how close the flows get with just ODs and travel times.
"""

from pathlib import Path
import sys

from dsf import logging

# The helpers shared by the toy models live in the parent folder
sys.path.append(str(Path(__file__).resolve().parent.parent))
import utils

HERE = Path(__file__).resolve().parent
INPUT_DIR = HERE / "../TransportationNetworks/Anaheim"
OUTPUT_DIR = HERE / "output"
NAME = "anaheim"
TITLE = "Anaheim"

LENGTH_UNIT = utils.FOOT
# Benchmark capacities are multiples of 1800 veh/h, i.e. the capacity of one lane
BENCHMARK_LANE_CAPACITY = 1800  # vehicles per hour
# Node coordinates are longitudes and latitudes
NODES_CRS = "EPSG:4326"
CENTROID_OFFSET = 0.002  # degrees
MAP_LINK_OFFSET = 120.0  # Web Mercator meters


def main(args):
    links = utils.read_tntp_network(INPUT_DIR / "Anaheim_net.tntp")
    n_zones = utils.read_n_zones(INPUT_DIR / "Anaheim_net.tntp")
    trips = utils.read_tntp_trips(INPUT_DIR / "Anaheim_trips.tntp")
    nodes = utils.read_geojson_nodes(INPUT_DIR / "anaheim_nodes.geojson")
    ue_flows = utils.read_tntp_flows(INPUT_DIR / "Anaheim_flow.tntp")
    logging.info(
        f"Loaded {links.height} links, {n_zones} zones and "
        f"{trips['trips'].sum():.0f} trips per hour."
    )

    # Zones are not through nodes: paths may not cross them
    utils.build_inputs(
        OUTPUT_DIR,
        links,
        trips,
        nodes,
        n_zones,
        length_unit=LENGTH_UNIT,
        centroid_offset=CENTROID_OFFSET,
        crossable_zones=False,
        benchmark_lane_capacity=BENCHMARK_LANE_CAPACITY,
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
        line_widths=(0.6, 4.0),
    )


if __name__ == "__main__":
    # The demand only fits within the link capacities over about 2 hours
    args = utils.parse_args(
        "Compare simulated and user-equilibrium link flows on Anaheim.",
        insertion_hours=2.0,
        hours=5,
    )
    OUTPUT_DIR.mkdir(exist_ok=True)
    main(args)
