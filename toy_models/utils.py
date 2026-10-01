"""
Shared helpers for the toy models: they read the TNTP files of the TransportationNetworks
repository, convert them into DSF inputs, run a traffic simulation fed only by the
origin-destination matrix, and compare the simulated link flows with the user-equilibrium ones.
"""

import argparse
import json
import re

import contextily as cx
import dsf
from dsf import logging, mobility
import geopandas as gpd
from matplotlib import pyplot as plt
from matplotlib.cm import ScalarMappable
from matplotlib.colors import BoundaryNorm, ListedColormap
import numpy as np
import polars as pl
from shapely.geometry import LineString

# Streets read their transport capacity from the edges file since dsf 7.3.1
assert tuple(map(int, re.findall(r"\d+", dsf.__version__)[:3])) >= (7, 3, 1), (
    f"The toy models require dsf >= 7.3.1 (found {dsf.__version__})"
)

MILE = 1609.344  # meters
FOOT = 0.3048  # meters
# A DSF lane releases at most one agent per second, i.e. 3600 veh/h: each link gets
# enough lanes for its capacity, and a transport capacity (the probability that a lane
# releases its front agent at each second) that brings it down to the benchmark one
LANE_CAPACITY = 3600  # vehicles per hour
# Origin and destination edges, and links with a zero free-flow time (which DSF cannot
# represent), are short links crossed in a few seconds
CONNECTOR_LENGTH = 50.0  # meters
CONNECTOR_SPEED_KPH = 50.0
DT_AGENT = 6  # seconds
SAVING_INTERVAL = 300  # seconds

GEH_THRESHOLD = 5
# Stepped diverging scale of the map, on the signed GEH (negative when the simulation
# underestimates the UE volume): a neutral gray for |GEH| < 5, then blue and red steps
# growing darker with the disagreement, the last ones open-ended
MAP_GEH_BOUNDS = [-30, -20, -10, -GEH_THRESHOLD, GEH_THRESHOLD, 10, 20, 30]
MAP_GEH_COLORS = [
    "#0d366b",
    "#1c5cab",
    "#3987e5",
    "#86b6ef",
    "#b9b9b4",
    "#f2a3a2",
    "#e34948",
    "#b52b2a",
    "#7a1515",
]
MAP_TILES = cx.providers.Esri.WorldGrayCanvas


# ----------------------------------------------------------------------------------------
# TNTP readers
# ----------------------------------------------------------------------------------------
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
                    "free_flow_time": float(tokens[4]),
                }
            )
    return pl.DataFrame(rows).with_row_index("id", offset=1)


def read_n_zones(file):
    """Read the number of zones from the metadata of a TNTP file."""
    with open(file) as f:
        return int(re.search(r"<NUMBER OF ZONES>\s*(\d+)", f.read()).group(1))


def read_tntp_trips(file):
    """Read the non-zero interzonal entries of a TNTP demand file."""
    with open(file) as f:
        text = f.read()
    rows = []
    for block in re.split(r"Origin\s+", text)[1:]:
        origin = int(block.split()[0])
        for destination, value in re.findall(r"(\d+)\s*:\s*([\d.]+)", block):
            if float(value) > 0 and int(destination) != origin:
                rows.append((origin, int(destination), float(value)))
    return pl.DataFrame(rows, schema=["origin", "destination", "trips"], orient="row")


def read_tntp_nodes(file):
    """Read the node coordinates of a TNTP node file (node, X, Y columns)."""
    nodes = pl.read_csv(file, separator="\t", truncate_ragged_lines=True)
    node, x, y = nodes.columns[:3]
    return nodes.select(
        pl.col(node).cast(pl.Int64).alias("id"),
        pl.col(x).cast(pl.Float64).alias("x"),
        pl.col(y).cast(pl.Float64).alias("y"),
    )


def read_geojson_nodes(file):
    """Read the node coordinates of a GeoJSON node file."""
    with open(file) as f:
        features = json.load(f)["features"]
    return pl.DataFrame(
        [
            {
                "id": feature["properties"]["id"],
                "x": float(feature["geometry"]["coordinates"][0]),
                "y": float(feature["geometry"]["coordinates"][1]),
            }
            for feature in features
        ]
    )


def read_tntp_flows(file):
    """Read the user-equilibrium link volumes of a TNTP flow file."""
    rows = []
    with open(file) as f:
        next(f)  # Skip the header
        for line in f:
            tokens = line.split()
            if tokens:
                rows.append((int(tokens[0]), int(tokens[1]), float(tokens[2])))
    return pl.DataFrame(rows, schema=["source", "target", "ue_flow"], orient="row")


# ----------------------------------------------------------------------------------------
# DSF inputs
# ----------------------------------------------------------------------------------------
def linestring(p, q):
    return f"LINESTRING ({p[0]} {p[1]}, {q[0]} {q[1]})"


def build_inputs(
    output_dir,
    links,
    trips,
    nodes,
    n_zones,
    length_unit,
    centroid_offset,
    crossable_zones,
    benchmark_lane_capacity=LANE_CAPACITY,
):
    """Write the edges, node properties and ODs files used by the simulator.

    Args:
        links: the network links, with lengths in `length_unit` meters and free-flow
            times in minutes.
        nodes: the node coordinates.
        length_unit: meters per unit of the link lengths.
        centroid_offset: distance of the centroids from their zone node, in the units of
            the node coordinates.
        crossable_zones: whether paths may go through the zone nodes. When they may not,
            the ingoing links of zone z end in a sink node ZONE_OFFSET + z instead.
        benchmark_lane_capacity: the lane capacity of the benchmark, in veh/h, which sets
            the number of lanes of each link.

    Zone z has an origin edge ZONE_OFFSET + z, from the centroid 2 * ZONE_OFFSET + z to
    the zone node, and a destination edge 2 * ZONE_OFFSET + z, from the zone (or sink)
    node to the centroid 3 * ZONE_OFFSET + z, both wide enough for the zone's demand.
    Agents depart on the origin edge and arrive at the start of the destination one, so
    that they are free to choose their first and last link.
    """
    # The smallest power of ten above every node and link id
    zone_offset = 10 ** len(str(max(nodes["id"].max(), links["id"].max())))
    coords = {row["id"]: (row["x"], row["y"]) for row in nodes.iter_rows(named=True)}
    zones = range(1, n_zones + 1)
    sinks = {} if crossable_zones else {zone_offset + z: coords[z] for z in zones}
    # Sink nodes share the position of their zone
    coords.update(sinks)

    zero_time = pl.col("free_flow_time") == 0
    length = pl.col("length") * length_unit
    edges = (
        links.with_columns(
            pl.format("{}-{}", "source", "target").alias("coilcode"),
            pl.when((pl.col("target") <= n_zones) & pl.lit(not crossable_zones))
            .then(pl.col("target") + zone_offset)
            .otherwise(pl.col("target"))
            .alias("target"),
            (pl.col("capacity") / benchmark_lane_capacity)
            .ceil()
            .cast(pl.Int64)
            .alias("nlanes"),
        )
        .select(
            "id",
            "source",
            "target",
            pl.when(zero_time).then(CONNECTOR_LENGTH).otherwise(length).alias("length"),
            pl.when(zero_time)
            .then(CONNECTOR_SPEED_KPH)
            .otherwise(length / (pl.col("free_flow_time") * 60) * 3.6)
            .alias("maxspeed"),
            "nlanes",
            "coilcode",
            (pl.col("capacity") / (pl.col("nlanes") * LANE_CAPACITY)).alias(
                "transport_capacity"
            ),
        )
        .with_columns(
            pl.struct("source", "target")
            .map_elements(
                lambda r: linestring(coords[r["source"]], coords[r["target"]]),
                return_dtype=pl.String,
            )
            .alias("geometry")
        )
    )

    produced = dict(trips.group_by("origin").agg(pl.col("trips").sum()).iter_rows())
    attracted = dict(
        trips.group_by("destination").agg(pl.col("trips").sum()).iter_rows()
    )
    zone_edges = []
    centroids = []
    for zone in zones:
        x, y = coords[zone]
        end = zone if crossable_zones else zone_offset + zone
        # Centroids only need a position distinct from their node, to give edges an angle
        origin_centroid = (x + centroid_offset, y + centroid_offset)
        destination_centroid = (x - centroid_offset, y - centroid_offset)
        centroids += [
            {
                "id": 2 * zone_offset + zone,
                "x": origin_centroid[0],
                "y": origin_centroid[1],
            },
            {
                "id": 3 * zone_offset + zone,
                "x": destination_centroid[0],
                "y": destination_centroid[1],
            },
        ]
        for edge_id, source, target, geometry, demand in [
            (
                zone_offset + zone,
                2 * zone_offset + zone,
                zone,
                linestring(origin_centroid, (x, y)),
                produced.get(zone, 0),
            ),
            (
                2 * zone_offset + zone,
                end,
                3 * zone_offset + zone,
                linestring((x, y), destination_centroid),
                attracted.get(zone, 0),
            ),
        ]:
            zone_edges.append(
                {
                    "id": edge_id,
                    "source": source,
                    "target": target,
                    "length": CONNECTOR_LENGTH,
                    "maxspeed": CONNECTOR_SPEED_KPH,
                    "nlanes": int(np.ceil(demand / LANE_CAPACITY)) + 1,
                    "coilcode": None,
                    "transport_capacity": None,
                    "geometry": geometry,
                }
            )
    edges = pl.concat(
        [edges, pl.DataFrame(zone_edges, schema=edges.schema)]
    ).with_columns(
        pl.lit(None, dtype=pl.String).alias("name"),
        pl.lit(None, dtype=pl.String).alias("type"),
    )
    edges.write_csv(output_dir / "edges.csv", separator=";")

    sink_nodes = pl.DataFrame(
        [{"id": i, "x": p[0], "y": p[1]} for i, p in sinks.items()],
        schema=nodes.schema,
    )
    pl.concat([nodes, sink_nodes, pl.DataFrame(centroids, schema=nodes.schema)]).select(
        "id",
        pl.lit(None, dtype=pl.String).alias("type"),
        pl.format("POINT ({} {})", "x", "y").alias("geometry"),
    ).write_csv(output_dir / "nodes.csv", separator=";")

    trips.select(
        (pl.col("origin") + zone_offset).alias("origin_id"),
        (pl.col("destination") + 2 * zone_offset).alias("destination_id"),
        pl.col("trips").alias("weight"),
    ).write_csv(output_dir / "ods.csv", separator=";")


# ----------------------------------------------------------------------------------------
# Simulation
# ----------------------------------------------------------------------------------------
def simulation(
    output_dir,
    name,
    total_trips,
    insertion_hours,
    hours,
    threshold,
    update_interval,
    intelligent_fraction,
    seed,
):
    """Run DSF on the inputs written by `build_inputs`.

    The OD matrix is an hourly demand: it is inserted evenly over `insertion_hours`,
    then the insertions stop and the network is left to empty until `hours`.
    """
    config = {
        "general": {
            "name": name,
            "input_folder": output_dir.as_posix(),
            "output_folder": output_dir.as_posix(),
            "output_basename": f"{name}_",
            "init_time": "20260101 000000",
            "update_paths": {
                "interval": update_interval,
                "throw_on_empty": False,
                # Fraction of agents following the paths updated on the current travel
                # times, the others keep the free-flow ones
                "intelligent_fraction": intelligent_fraction,
            },
            "save_data": {"interval": SAVING_INTERVAL, "avg": True, "road": True},
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
    config_file = output_dir / "simconfig.json"
    with config_file.open("w") as f:
        json.dump(config, f, indent=4)

    # The simulator appends to its output files
    for table in ["road_data", "avg_stats"]:
        (output_dir / f"{name}_{table}.csv").unlink(missing_ok=True)

    simulator = mobility.TrafficSimulator(config_file.as_posix())
    load_steps = round(insertion_hours * 3600 / DT_AGENT)
    cumulative = np.floor(np.arange(load_steps + 1) * total_trips / load_steps)
    schedule = np.diff(cumulative).astype(np.int64).tolist()
    schedule += [0] * (hours * 3600 // DT_AGENT - load_steps)
    simulator.run(schedule, DT_AGENT)


# ----------------------------------------------------------------------------------------
# Comparison with the user equilibrium
# ----------------------------------------------------------------------------------------
def geh(simulated, reference):
    """GEH statistic of simulated against reference hourly volumes."""
    return np.sqrt(
        2 * (simulated - reference) ** 2 / np.maximum(simulated + reference, 1)
    )


def compare(output_dir, name, title, links, ue_flows, insertion_hours, hours):
    """Compare the simulated link volumes with the UE ones, and plot them.

    Returns the comparison table, with one row per benchmark link.
    """
    road_data = pl.read_csv(
        output_dir / f"{name}_road_data.csv", separator=";", infer_schema_length=None
    )
    avg_stats = pl.read_csv(
        output_dir / f"{name}_avg_stats.csv", separator=";", infer_schema_length=None
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
    df.write_csv(output_dir / "flows_comparison.csv", separator=";")

    ue = df["ue_flow"].to_numpy()
    sim = df["sim_flow"].to_numpy()
    r2 = 1 - np.sum((sim - ue) ** 2) / np.sum((ue - ue.mean()) ** 2)
    pearson = np.corrcoef(ue, sim)[0, 1]
    loaded = ue > 0
    logging.info(
        f"Link volumes: Pearson r = {pearson:.3f}, R2 = {r2:.3f}, "
        f"total simulated / UE = {sim.sum() / ue.sum():.3f}, "
        f"median relative error = {np.median(np.abs(sim - ue)[loaded] / ue[loaded]):.1%}, "
        f"links with GEH < {GEH_THRESHOLD}: {np.mean(geh(sim, ue) < GEH_THRESHOLD):.0%}"
    )

    fig, (ax_flows, ax_agents) = plt.subplots(1, 2, figsize=(13, 6))
    ax_flows.scatter(
        ue,
        sim,
        c=ue / df["capacity"].to_numpy(),
        cmap="viridis",
        s=12 if df.height < 1000 else 6,
        alpha=1 if df.height < 1000 else 0.7,
    )
    fig.colorbar(ax_flows.collections[0], ax=ax_flows, label="UE volume / capacity")
    top = max(ue.max(), sim.max()) * 1.05
    ax_flows.plot([0, top], [0, top], "k--", lw=1, label="y = x")
    ax_flows.set_xlabel("User-equilibrium volume (veh)")
    ax_flows.set_ylabel("Simulated volume (veh)")
    ax_flows.set_title(f"Link volumes (Pearson r = {pearson:.2f}, $R^2$ = {r2:.2f})")
    ax_flows.legend()
    ax_flows.grid(ls="--", alpha=0.7)

    ax_agents.plot(avg_stats["time_step"] / 3600, avg_stats["n_agents"])
    ax_agents.axvspan(
        0, insertion_hours, color="gray", alpha=0.2, label="Demand insertion"
    )
    ax_agents.set_xlabel("Time (h)")
    ax_agents.set_ylabel("Number of agents")
    ax_agents.set_title("Agents in the network")
    ax_agents.legend()
    ax_agents.grid(ls="--", alpha=0.7)

    fig.suptitle(f"{title}: simulated vs user-equilibrium link flows")
    fig.tight_layout()
    fig.savefig(output_dir / "flows_comparison.pdf")
    plt.close(fig)
    return df


def plot_map(
    output_dir,
    title,
    df,
    nodes,
    crs,
    link_offset,
    panels=None,
    line_widths=(0.4, 3.0),
):
    """Map the links over a real tile, colored by the signed GEH of their simulated volume.

    Args:
        df: the comparison table returned by `compare`.
        nodes: the node coordinates, in the `crs` reference system.
        link_offset: the shift of each link to its right, so that opposite directions do
            not overlap, in Web Mercator meters.
        panels: a list of (title, view) pairs, one per panel. The view is None for the
            whole network, or (longitude, latitude, half width in Web Mercator meters)
            for a zoom. Defaults to a single panel with the whole network.
        line_widths: the widths of the least and most loaded links, which grow with the
            UE volume.
    """
    points = gpd.GeoSeries(gpd.points_from_xy(nodes["x"], nodes["y"]), crs=crs).to_crs(
        epsg=3857
    )
    coords = dict(zip(nodes["id"], zip(points.x, points.y)))
    ue = df["ue_flow"].to_numpy()
    sim = df["sim_flow"].to_numpy()
    signed_geh = np.sign(sim - ue) * geh(sim, ue)
    cmap = ListedColormap(MAP_GEH_COLORS)
    norm = BoundaryNorm(MAP_GEH_BOUNDS, cmap.N, extend="both")
    links = gpd.GeoDataFrame(
        {
            "color": list(cmap(norm(signed_geh))),
            "width": line_widths[0] + (line_widths[1] - line_widths[0]) * ue / ue.max(),
            "disagreement": np.abs(signed_geh),
        },
        geometry=[
            LineString([coords[s], coords[t]]).offset_curve(-link_offset)
            for s, t in zip(df["source"], df["target"])
        ],
        crs="EPSG:3857",
    ).sort_values("disagreement")

    panels = panels or [(None, None)]
    extents = []
    for _, view in panels:
        if view is None:
            x0, y0, x1, y1 = links.total_bounds
            pad = 0.03 * max(x1 - x0, y1 - y0)
            extents.append((x0 - pad, x1 + pad, y0 - pad, y1 + pad))
        else:
            lon, lat, half_width = view
            center = gpd.GeoSeries(
                gpd.points_from_xy([lon], [lat]), crs="EPSG:4326"
            ).to_crs(epsg=3857)[0]
            extents.append(
                (
                    center.x - half_width,
                    center.x + half_width,
                    center.y - half_width,
                    center.y + half_width,
                )
            )
    # Size the figure on the shape of the maps, with room for the title and color bar
    panel_width = 8
    aspect = max((y1 - y0) / (x1 - x0) for x0, x1, y0, y1 in extents)
    map_height = min(max(panel_width * aspect, 4), 12)
    colorbar_height = 1.4
    height = map_height + colorbar_height + 0.6
    width = panel_width * len(panels)
    fig, axes = plt.subplots(1, len(panels), figsize=(width, height))
    axes = np.atleast_1d(axes)
    for ax, (panel_title, _), (x0, x1, y0, y1) in zip(axes, panels, extents):
        # Links sorted by disagreement, so that the largest errors are drawn on top
        links.plot(ax=ax, color=links["color"], linewidth=links["width"])
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        if panel_title:
            ax.set_title(panel_title)
        ax.set_axis_off()
        try:
            cx.add_basemap(ax, source=MAP_TILES)
        # Tiles fail in many ways (offline, provider errors): the map is still useful
        except Exception as error:  # noqa: BLE001
            logging.warn(f"Could not download the map tiles ({error}).")

    good = np.mean(np.abs(signed_geh) < GEH_THRESHOLD)
    fig.suptitle(
        f"{title}: link volume errors ({good:.0%} of the links with |GEH| < "
        f"{GEH_THRESHOLD})"
    )
    fig.tight_layout(rect=(0, colorbar_height / height, 1, 1))
    bar_width = min(6 / width, 0.8)
    cax = fig.add_axes((0.5 - bar_width / 2, 0.75 / height, bar_width, 0.2 / height))
    colorbar = fig.colorbar(
        ScalarMappable(norm=norm, cmap=cmap),
        cax=cax,
        orientation="horizontal",
        extend="both",
        spacing="uniform",
    )
    colorbar.set_label(
        "Signed GEH of the simulated volume against the UE one\n"
        "blue: underestimated, gray: good match, red: overestimated; "
        "line width: UE volume"
    )
    fig.savefig(output_dir / "flows_map.pdf")
    plt.close(fig)


# ----------------------------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------------------------
def parse_args(description, insertion_hours, hours):
    """Parse the options shared by the toy models, with their defaults."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--insertion-hours",
        help="Hours over which the hourly demand is inserted "
        f"(default: {insertion_hours:g}).",
        type=float,
        default=insertion_hours,
    )
    parser.add_argument(
        "--hours",
        help=f"Simulated hours, including the insertion ones (default: {hours}).",
        type=int,
        default=hours,
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
    if args.hours < args.insertion_hours:
        parser.error("--hours must cover --insertion-hours")
    return args
