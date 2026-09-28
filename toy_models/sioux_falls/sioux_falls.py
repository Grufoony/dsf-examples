"""
Script to simulate the Sioux Falls benchmark network using the DSF library.
The script converts the TNTP files of the TransportationNetworks repository into DSF inputs,
runs a traffic simulation fed only by the origin-destination matrix, with agents routed on the
current travel times, and compares the simulated link flows with the user-equilibrium ones.

Nothing is calibrated: the goal is to see how close the flows get with just ODs and travel times.
"""

import argparse
import json
import math
import re
from pathlib import Path

import dsf
from dsf import logging, mobility
from matplotlib import pyplot as plt
import numpy as np
import polars as pl

assert tuple(map(int, dsf.__version__.split(".")[:2])) >= (7, 3), (
    f"This example requires dsf >= 7.3.0 (found {dsf.__version__})"
)

INPUT_DIR = Path("../TransportationNetworks/SiouxFalls")
OUTPUT_DIR = Path("output")
OUTPUT_BASENAME = "sioux_falls_"

# Link lengths are equal to free-flow times: reading them as miles and minutes gives 60 mph
MILE = 1609.344  # meters
MAX_SPEED_KPH = 60 * MILE / 1000
# A DSF lane releases at most one agent per second
LANE_CAPACITY = 3600  # vehicles per hour
CONNECTOR_LENGTH = 50.0  # meters
# Ids of centroids and connectors: zone z has centroid ZONE_OFFSET + z,
# origin connector ZONE_OFFSET + z and destination connector 2 * ZONE_OFFSET + z
ZONE_OFFSET = 100
DT_AGENT = 6  # seconds


def read_tntp_network(file):
    """Read the links of a TNTP network file, numbered from 1 in file order."""
    rows = []
    with open(file) as f:
        # Skip the metadata block
        for line in f:
            if line.strip().startswith("<END OF METADATA>"):
                break
        for line in f:
            tokens = line.strip().rstrip(";").split()
            if not tokens or tokens[0].startswith("~"):
                continue
            rows.append(
                {
                    "source": int(tokens[0]),
                    "target": int(tokens[1]),
                    "capacity": float(tokens[2]),
                    "length": float(tokens[3]),
                }
            )
    return pl.DataFrame(rows).with_row_index("id", offset=1)


def read_tntp_trips(file):
    """Read the non-zero entries of a TNTP demand file."""
    with open(file) as f:
        text = f.read()
    rows = []
    for block in re.split(r"Origin\s+", text)[1:]:
        origin = int(block.split()[0])
        for destination, value in re.findall(r"(\d+)\s*:\s*([\d.]+)", block):
            if float(value) > 0 and int(destination) != origin:
                rows.append(
                    {
                        "origin": origin,
                        "destination": int(destination),
                        "trips": float(value),
                    }
                )
    return pl.DataFrame(rows)


def read_tntp_nodes(file):
    """Read the node coordinates of a TNTP node file."""
    return pl.read_csv(file, separator="\t", truncate_ragged_lines=True).select(
        pl.col("Node").alias("id"), pl.col("X").alias("x"), pl.col("Y").alias("y")
    )


def read_tntp_flows(file):
    """Read the user-equilibrium link volumes of a TNTP flow file."""
    rows = []
    with open(file) as f:
        next(f)  # Skip the header
        for line in f:
            tokens = line.split()
            if tokens:
                rows.append(
                    {
                        "source": int(tokens[0]),
                        "target": int(tokens[1]),
                        "ue_flow": float(tokens[2]),
                    }
                )
    return pl.DataFrame(rows)


def linestring(p, q):
    return f"LINESTRING ({p[0]} {p[1]}, {q[0]} {q[1]})"


def build_inputs(links, trips, nodes):
    """Write the edges, node properties and ODs files used by the simulator."""
    coords = {row["id"]: (row["x"], row["y"]) for row in nodes.iter_rows(named=True)}

    edges = links.select(
        "id",
        "source",
        "target",
        (pl.col("length") * MILE).alias("length"),
        pl.lit(MAX_SPEED_KPH).alias("maxspeed"),
        (pl.col("capacity") / LANE_CAPACITY).ceil().cast(pl.Int64).alias("nlanes"),
        pl.format("{}-{}", "source", "target").alias("coilcode"),
    ).with_columns(
        pl.struct("source", "target")
        .map_elements(
            lambda r: linestring(coords[r["source"]], coords[r["target"]]),
            return_dtype=pl.String,
        )
        .alias("geometry")
    )

    # Each zone is a centroid linked to its node by two connectors, wide enough to carry
    # the zone's demand: agents depart on the origin one and arrive at the start of the
    # destination one, so that they are free to choose their first and last link
    produced = trips.group_by("origin").agg(pl.col("trips").sum())
    attracted = trips.group_by("destination").agg(pl.col("trips").sum())
    connectors = []
    centroids = []
    for zone in nodes["id"]:
        x, y = coords[zone]
        # Centroids only need a position distinct from their node, to give connectors an angle
        centroid = (x + 0.002, y + 0.002)
        centroids.append({"id": ZONE_OFFSET + zone, "x": centroid[0], "y": centroid[1]})
        for connector_id, source, target, geometry, demand in [
            (
                ZONE_OFFSET + zone,
                ZONE_OFFSET + zone,
                zone,
                linestring(centroid, (x, y)),
                produced.filter(pl.col("origin") == zone)["trips"].sum(),
            ),
            (
                2 * ZONE_OFFSET + zone,
                zone,
                ZONE_OFFSET + zone,
                linestring((x, y), centroid),
                attracted.filter(pl.col("destination") == zone)["trips"].sum(),
            ),
        ]:
            connectors.append(
                {
                    "id": connector_id,
                    "source": source,
                    "target": target,
                    "length": CONNECTOR_LENGTH,
                    "maxspeed": MAX_SPEED_KPH,
                    "nlanes": math.ceil(demand / LANE_CAPACITY) + 1,
                    "coilcode": None,
                    "geometry": geometry,
                }
            )
    edges = pl.concat(
        [edges, pl.DataFrame(connectors, schema=edges.schema)]
    ).with_columns(
        pl.lit(None, dtype=pl.String).alias("name"),
        pl.lit(None, dtype=pl.String).alias("type"),
    )
    edges.write_csv(OUTPUT_DIR / "edges.csv", separator=";")

    pl.concat([nodes, pl.DataFrame(centroids, schema=nodes.schema)]).select(
        "id",
        pl.lit(None, dtype=pl.String).alias("type"),
        pl.format("POINT ({} {})", "x", "y").alias("geometry"),
    ).write_csv(OUTPUT_DIR / "nodes.csv", separator=";")

    trips.select(
        (pl.col("origin") + ZONE_OFFSET).alias("origin_id"),
        (pl.col("destination") + 2 * ZONE_OFFSET).alias("destination_id"),
        pl.col("trips").alias("weight"),
    ).write_csv(OUTPUT_DIR / "ods.csv", separator=";")


def simulation(
    total_trips, hours, threshold, update_interval, intelligent_fraction, seed
):
    config = {
        "general": {
            "name": "sioux_falls",
            "input_folder": OUTPUT_DIR.as_posix(),
            "output_folder": OUTPUT_DIR.as_posix(),
            "output_basename": OUTPUT_BASENAME,
            "init_time": "20260101 000000",
            "update_paths": {
                "interval": update_interval,
                "throw_on_empty": False,
                # Fraction of agents following the paths updated on the current travel
                # times, the others keep the free-flow ones
                "intelligent_fraction": intelligent_fraction,
            },
            "save_data": {"interval": 300, "avg": True, "road": True},
        },
        "road_network": {
            "edges_file": "edges.csv",
            "node_properties_file": "nodes.csv",
            "set_edge_weight": {"weight": "traveltime", "threshold": threshold},
        },
        "dynamics": {
            "seed": seed,
            "agent_insertion_method": "ODS",
            "importODsFromCSV": {"file": "ods.csv", "separator": ";", "edges": True},
        },
    }
    config_file = OUTPUT_DIR / "simconfig.json"
    with config_file.open("w") as f:
        json.dump(config, f, indent=4)

    # The simulator appends to its output files
    for table in ["road_data", "avg_stats"]:
        (OUTPUT_DIR / f"{OUTPUT_BASENAME}{table}.csv").unlink(missing_ok=True)

    simulator = mobility.TrafficSimulator(config_file.as_posix())
    # The OD matrix is an hourly demand: insert it evenly during the first hour,
    # then stop the insertions and let the network empty
    load_steps = 3600 // DT_AGENT
    cumulative = np.floor(np.arange(load_steps + 1) * total_trips / load_steps)
    schedule = np.diff(cumulative).astype(np.int64).tolist()
    schedule += [0] * ((hours - 1) * 3600 // DT_AGENT)
    simulator.run(schedule, DT_AGENT)


def compare(links, ue_flows, hours):
    road_data = pl.read_csv(
        OUTPUT_DIR / f"{OUTPUT_BASENAME}road_data.csv",
        separator=";",
        infer_schema_length=None,
    )
    avg_stats = pl.read_csv(
        OUTPUT_DIR / f"{OUTPUT_BASENAME}avg_stats.csv",
        separator=";",
        infer_schema_length=None,
    )
    # A static assignment volume is the number of trips using a link: count every
    # traversal over the whole run, so that each trip is counted once per link
    sim_flows = (
        road_data.filter(pl.col("coil").is_not_null())
        .group_by("street_id")
        .agg(pl.col("counts").sum().alias("sim_flow"))
    )
    n_remaining = avg_stats["n_agents"][-1]
    if n_remaining > 0:
        logging.warn(
            f"{n_remaining} agents are still travelling after {hours} hours: "
            "their trips are only partially counted. Consider increasing --hours."
        )
    df = (
        links.join(ue_flows, on=["source", "target"])
        .join(sim_flows, left_on="id", right_on="street_id", how="left")
        .with_columns(pl.col("sim_flow").fill_null(0))
        .select("id", "source", "target", "capacity", "ue_flow", "sim_flow")
        .sort("id")
    )
    df.write_csv(OUTPUT_DIR / "flows_comparison.csv", separator=";")

    ue = df["ue_flow"].to_numpy()
    sim = df["sim_flow"].to_numpy()
    r2 = 1 - np.sum((sim - ue) ** 2) / np.sum((ue - ue.mean()) ** 2)
    pearson = np.corrcoef(ue, sim)[0, 1]
    geh = np.sqrt(2 * (sim - ue) ** 2 / np.maximum(sim + ue, 1))
    logging.info(
        f"Link volumes: Pearson r = {pearson:.3f}, R2 = {r2:.3f}, "
        f"total simulated / UE = {sim.sum() / ue.sum():.3f}, "
        f"median relative error = {np.median(np.abs(sim - ue) / ue):.1%}, "
        f"links with GEH < 5: {np.mean(geh < 5):.0%}"
    )

    fig, (ax_flows, ax_agents) = plt.subplots(1, 2, figsize=(13, 6))
    ax_flows.scatter(ue, sim, c=ue / df["capacity"].to_numpy(), cmap="viridis")
    fig.colorbar(ax_flows.collections[0], ax=ax_flows, label="UE volume / capacity")
    top = max(ue.max(), sim.max()) * 1.05
    ax_flows.plot([0, top], [0, top], "k--", lw=1, label="y = x")
    ax_flows.set_xlabel("User-equilibrium volume (veh)")
    ax_flows.set_ylabel("Simulated volume (veh)")
    ax_flows.set_title(f"Link volumes (Pearson r = {pearson:.2f}, $R^2$ = {r2:.2f})")
    ax_flows.legend()
    ax_flows.grid(ls="--", alpha=0.7)

    ax_agents.plot(avg_stats["time_step"] / 3600, avg_stats["n_agents"])
    ax_agents.axvspan(0, 1, color="gray", alpha=0.2, label="Demand insertion")
    ax_agents.set_xlabel("Time (h)")
    ax_agents.set_ylabel("Number of agents")
    ax_agents.set_title("Agents in the network")
    ax_agents.legend()
    ax_agents.grid(ls="--", alpha=0.7)

    fig.suptitle("Sioux Falls: simulated vs user-equilibrium link flows")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "flows_comparison.pdf")


def main(
    hours=3, threshold=0.05, update_interval=300, intelligent_fraction=1.0, seed=69
):
    links = read_tntp_network(INPUT_DIR / "SiouxFalls_net.tntp")
    trips = read_tntp_trips(INPUT_DIR / "SiouxFalls_trips.tntp")
    nodes = read_tntp_nodes(INPUT_DIR / "SiouxFalls_node.tntp")
    ue_flows = read_tntp_flows(INPUT_DIR / "SiouxFalls_flow.tntp")
    logging.info(
        f"Loaded {links.height} links, {nodes.height} zones and {trips['trips'].sum():.0f} trips per hour."
    )

    build_inputs(links, trips, nodes)
    simulation(
        trips["trips"].sum(),
        hours,
        threshold,
        update_interval,
        intelligent_fraction,
        seed,
    )
    compare(links, ue_flows, hours)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compare simulated and user-equilibrium link flows on Sioux Falls."
    )
    parser.add_argument(
        "--hours",
        help="Simulated hours: the demand is inserted in the first one (default: 3).",
        type=int,
        default=3,
    )
    parser.add_argument(
        "--threshold",
        help="Relative tolerance for equivalent paths (default: 0.05).",
        type=float,
        default=0.05,
    )
    parser.add_argument(
        "--update-interval",
        help="Seconds between path updates (default: 300).",
        type=int,
        default=300,
    )
    parser.add_argument(
        "--intelligent-fraction",
        help="Fraction of agents following the updated paths (default: 1.0).",
        type=float,
        default=1.0,
    )
    parser.add_argument(
        "--seed",
        help="The random seed to use (default: 69).",
        type=int,
        default=69,
    )
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(exist_ok=True)
    main(
        args.hours,
        args.threshold,
        args.update_interval,
        args.intelligent_fraction,
        args.seed,
    )
