# Sioux Falls
To run the simulation, with `dsf-suite` >= 7.3.0:
```shell
python sioux_falls.py
```

This will create a new `output` folder with the generated DSF inputs, the simulation data, the table `flows_comparison.csv` and the plot `flows_comparison.pdf`.
Run `python sioux_falls.py --help` to change the simulated hours, the path threshold, the path update interval or the seed.

The network data are read from the `TransportationNetworks` submodule, so be sure to have it checked out (see the main README).

## Motivation
Sioux Falls is the most used benchmark in traffic assignment: a small network with a known user-equilibrium (UE) solution.
The question is whether DSF gets close to the UE link flows starting from just the origin-destination matrix and agents routed on travel times, without calibrating anything.

## Setup
The TNTP files are translated into DSF inputs as follows:
- **Links**: the benchmark link lengths equal the free-flow times, so they are read as miles and minutes, i.e. 60 mph on every link. The number of lanes is `ceil(capacity / 3600)`, since a DSF lane releases at most one vehicle per second.
- **Zones**: every zone is a centroid linked to its node by an origin and a destination connector, wide enough for the zone's demand. Agents are then free to choose their first and last link.
- **Demand**: the OD matrix (360,600 trips) is read as hourly. It is inserted evenly during the first hour; afterwards the network is left to empty.
- **Routing**: every agent follows the paths computed on the current travel times (free-flow time plus queue delay), updated every 300 seconds. Paths within 5% of the best one are considered equivalent.

Every link traversal is counted over the whole run, so the simulated volume of a link is the number of trips using it, i.e. the same quantity as a static assignment volume.

## Results
All trips arrive within about 2.5 hours, with no gridlock.
The simulated link volumes follow the UE ones with Pearson r ≈ 0.92–0.93 and R² ≈ 0.83–0.85, and the total volume is within 2–3% of the UE one.
The ranges come from repeated runs: the results change slightly between runs even with the same seed.

The largest deviations have a pattern. Low-capacity links (≈ 4,900 veh/h) are overloaded by up to +55%, while the main corridor links (10–15, 15–19, 9–10) are underloaded by about 20%.
This follows from the lane rounding: 4,900 veh/h becomes 2 lanes, i.e. 1.47 times the benchmark capacity, while 13,500 veh/h becomes 4 lanes, only 1.07 times.

### Fraction of intelligent agents
Only intelligent agents follow the updated paths: the others keep the free-flow ones.
Changing the fraction with `--intelligent-fraction` gives (3 runs each):

| Fraction | Pearson r | R² | Network empty after |
|---|---|---|---|
| 0.0 | 0.53 | < 0 | > 5 h (partial counts) |
| 0.25 | 0.64 | 0.16–0.17 | ~4.4 h |
| 0.5 | 0.81–0.82 | 0.63–0.65 | ~3.2 h |
| 0.75 | 0.91–0.92 | 0.82–0.83 | ~2.7 h |
| 0.9 | 0.93–0.94 | 0.86–0.87 | < 3 h |
| 1.0 | 0.92–0.93 | 0.84–0.85 | ~2.5 h |

The flows get closer to the UE ones as more agents react to congestion, since free-flow paths overload the shortest routes.
The best match is slightly below 1: probably a small share of agents keeping their paths damps the flows swinging between routes at each path update.

The benchmark demand is not a steady state that DSF can reach. The UE solution loads links up to 2.5 times their capacity, which the BPR cost function allows.
A maximum concurrent flow computation shows that, even with ideal routing, only about 67% of the hourly demand fits within the DSF link capacities (52% within the BPR capacities).
Inserting the demand for more than one hour only makes the queues grow: this is why the demand is inserted once and the whole run is counted.

## Data
Network, demand, node coordinates and UE flows are taken from [TransportationNetworks](https://github.com/bstabler/TransportationNetworks/tree/master/SiouxFalls).
