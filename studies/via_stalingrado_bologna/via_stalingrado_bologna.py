"""
Script to simulate the traffic flow at Via Stalingrado, Bologna (Italy) using the DSF library.
The script reads an input file specifying the time unit and the number of vehicles to insert at each time step, runs a traffic simulation, and outputs the flow data to a CSV file.
Finally, it generates a plot comparing the input and output flow over time.

The goal is to show the effect of traffic lights on the vehicle flow.
"""

from pathlib import Path

from dsf import mobility
from matplotlib import pyplot as plt
import polars as pl
import tqdm

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")


def simulation(time_unit, vehicles_to_insert, out):
    MAX_TIME = time_unit * len(vehicles_to_insert)

    # Build network
    graph = mobility.RoadNetwork()

    # Set global mean vehicle length
    mobility.Street.setMeanVehicleLength(8.0)

    # Add nodes (0..4)
    for nid in range(5):
        graph.addNode(nid)

    # Add streets (id, source, target, length, maxSpeed, nLanes)
    graph.addStreet(1, 0, 1, 2281.0, 13.9, 2, "")
    graph.addStreet(7, 1, 2, 118.0, 13.9, 2, "")
    graph.addStreet(13, 2, 3, 222.0, 13.9, 2, "")
    graph.addStreet(19, 3, 4, 651.0, 13.9, 2, "")

    # Create traffic lights on nodes 1..4 and set cycles
    tl1 = graph.makeTrafficLight(1, 132)
    tl1.setCycle(1, mobility.Direction.ANY, mobility.TrafficLightCycle(62, 0))

    tl2 = graph.makeTrafficLight(2, 141)
    tl2.setCycle(7, mobility.Direction.ANY, mobility.TrafficLightCycle(72, 0))

    tl3 = graph.makeTrafficLight(3, 138)
    tl3.setCycle(13, mobility.Direction.ANY, mobility.TrafficLightCycle(88, 0))

    tl4 = graph.makeTrafficLight(4, 131)
    tl4.setCycle(19, mobility.Direction.ANY, mobility.TrafficLightCycle(81, 0))

    graph.adjustNodeCapacities()
    graph.addCoil(19)
    coil = graph.edge(19)

    # Create dynamics
    dynamics = mobility.Dynamics(graph, False, 69)
    dynamics.setODs([(0, 4, 1.0)])
    dynamics.updatePaths()

    it_index = 0
    df = pl.DataFrame(
        schema={
            "time": pl.Int64,
            "input_flow": pl.Int64,
            "output_flow": pl.Int64,
        }
    )

    added_vehicles = 0

    for progress in tqdm.tqdm(range(0, MAX_TIME), desc="Simulating"):
        if progress % 60 == 0:
            if progress != 0:
                it_index += 1
            if progress % 300 == 0:
                df = df.vstack(
                    pl.DataFrame(
                        {
                            "time": [progress],
                            "input_flow": [added_vehicles],
                            "output_flow": [coil.counts()],
                        }
                    )
                )
                coil.resetCounter()
                added_vehicles = 0
            # number of agents to insert at this step
            n = (
                vehicles_to_insert[it_index]
                if it_index < len(vehicles_to_insert)
                else 0
            )
            if n > 0:
                # Use uniform insertion assigning the itinerary id (4)
                dynamics.addAgentsUniformly(n, 4)
                added_vehicles += n
        dynamics.evolve()

    df.write_csv(out, separator=";")
    print("\nSimulation finished.")


def plot(output_file):
    out_flow_df = pl.read_csv(output_file, separator=";")

    plt.figure(figsize=(10, 6))
    plt.plot(
        out_flow_df["time"], out_flow_df["input_flow"], label="Input Flow", marker="o"
    )
    plt.plot(
        out_flow_df["time"], out_flow_df["output_flow"], label="Output Flow", marker="x"
    )
    plt.xlabel("Time (ticks)")
    plt.ylabel("Number of Vehicles")
    plt.title("Input vs Output Flow at Via Stalingrado, Bologna (Italy)")
    plt.legend()
    plt.grid(ls="--", alpha=0.7)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "flow_comparison.pdf")


def main():
    input_file = INPUT_DIR / "input_flow.txt"

    OUTPUT_DIR.mkdir(exist_ok=True)
    output_file = OUTPUT_DIR / "output_flow.csv"

    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    with input_file.open() as f:
        toks = [t for t in f.read().split() if t.strip()]
    if not toks:
        raise RuntimeError("Empty input file")

    time_unit = int(toks[0])
    vehicles_to_insert = [int(x) for x in toks[1:]]
    if not vehicles_to_insert:
        raise RuntimeError("No vehicle insertion schedule found in input file")
    simulation(time_unit, vehicles_to_insert, output_file)

    if not output_file.exists():
        raise FileNotFoundError(f"Output file not found: {output_file}")
    plot(output_file)


if __name__ == "__main__":
    main()
