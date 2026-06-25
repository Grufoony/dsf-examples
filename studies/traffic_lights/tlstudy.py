"""
Python translation of tlstudy.cpp: simple traffic-light chain simulation

Usage:
    python studies/traffic_lights/tlstudy.py N_MAX SEED [--alpha ALPHA]

This script mirrors the behavior of the C++ example: it builds a chain of
streets and traffic lights, runs a dynamics simulation adding agents
probabilistically, and writes periodic input/output flow to CSV files.
"""

from pathlib import Path
import argparse
import random
import numpy as np

from dsf import mobility


MAX_TIME = int(75e3 * 4)
ROAD_LENGTH = 6e2


def main():
    parser = argparse.ArgumentParser(description="Traffic lights chain simulation")
    parser.add_argument("N_MAX", type=int)
    parser.add_argument("SEED", type=int)
    parser.add_argument("--alpha", type=float, default=0.01)
    args = parser.parse_args()

    np.random.seed(args.SEED)

    for N_TRAFFICLIGHTS in range(1, args.N_MAX + 1):
        alpha = args.alpha
        print(f"Simulating with {N_TRAFFICLIGHTS} traffic lights...")

        # Use a deterministic RNG seeded the same way as the C++ example
        rng = random.Random()
        rng.seed(args.SEED)

        # sample a (single) phase length for this run
        length = rng.gauss(60.0, 10.0)
        phase_max = max(0, int(length * 2))

        # Build network
        graph = mobility.RoadNetwork()

        # create N_TRAFFICLIGHTS+1 streets connecting nodes 0..N_TRAFFICLIGHTS
        for sid in range(N_TRAFFICLIGHTS + 1):
            graph.addStreet(sid, sid, sid + 1, ROAD_LENGTH, 13.9, 2, "")
            graph.addCoil(sid)

        # create traffic lights on nodes 1..N_TRAFFICLIGHTS
        for tid in range(N_TRAFFICLIGHTS):
            node_id = tid + 1
            graph.makeTrafficLight(node_id)
            tl = graph.node(node_id)
            street = graph.edge(tid)

            # detect street id accessor
            try:
                street_id = street.id()
            except Exception:
                street_id = getattr(street, "id", None)

            tl.addPhase(mobility.TrafficLightPhase(int(length), {street_id: {mobility.Direction.ANY}}))
            tl.addPhase(mobility.TrafficLightPhase(int(length)))

            # randomize starting offset if available
            phase_offset = rng.randint(0, phase_max) if phase_max > 0 else 0
            if hasattr(tl, "advanceBy"):
                try:
                    tl.advanceBy(phase_offset)
                except Exception:
                    pass

            # optionally log final traffic-light settings for the last run
            if N_TRAFFICLIGHTS == args.N_MAX:
                try:
                    p = Path(f"./traffic_light_settings_{args.SEED}.log")
                    with p.open("a") as logf:
                        logf.write(f"{tl}\n")
                except Exception:
                    pass

        graph.adjustNodeCapacities()
        output_road = graph.edge(N_TRAFFICLIGHTS)

        # instantiate dynamics
        dynamics = mobility.Dynamics(graph, False, args.SEED)
        graph = dynamics.graph()
        dynamics.setODs([(0, N_TRAFFICLIGHTS + 1, 1.0)])
        dynamics.updatePaths()

        out_path = Path(f"./{args.SEED}_traffic_light_output_{N_TRAFFICLIGHTS}.csv")
        with out_path.open("w") as ofs:
            ofs.write("time;input_flow;output_flow")
            for idx in range(N_TRAFFICLIGHTS + 1):
                ofs.write(f";queue_{idx};density_{idx};counts_{idx}")
            ofs.write("\n")
            totAgents = 0

            for progress in range(0, MAX_TIME + 1):
                if progress > 0 and progress % 300 == 0:
                    ofs.write(f"{progress};{totAgents};{output_road.counts()}")
                    for idx in range(N_TRAFFICLIGHTS + 1):
                        road = graph.edge(idx)
                        ofs.write(f";{road.nExitingAgents()};{road.density(True)};{road.counts()}")
                        road.resetCounter()
                    ofs.write("\n")
                    totAgents = 0
                    output_road.resetCounter()

                # probabilistic insertion
                # decimal_part, integer_part = math.modf(alpha)
                # if integer_part > 0:
                #     dynamics.addAgents(int(integer_part), mobility.AgentInsertionMethod.ODS)
                #     totAgents += int(integer_part)
                # if rng.random() < decimal_part:
                #     dynamics.addAgents(1, mobility.AgentInsertionMethod.ODS)
                #     totAgents += 1
                agents_to_add = np.random.poisson(alpha)
                dynamics.addAgents(agents_to_add, mobility.AgentInsertionMethod.ODS)
                totAgents += agents_to_add

                if progress > 0 and progress % 2500 == 0:
                    alpha += 0.01
                    print(f"Time: {progress}, alpha: {alpha:.2f}")

                # advance the simulation
                dynamics.evolve()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
