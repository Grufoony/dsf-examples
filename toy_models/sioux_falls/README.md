# Sioux Falls
To run the simulation, with `dsf-suite` >= 7.3.1:
```shell
python sioux_falls.py
```

This will create a new `output` folder with the generated DSF inputs, the simulation data, the table `flows_comparison.csv`, the plot `flows_comparison.pdf` and the map `flows_map.pdf` (also as `flows_map.png`).
Run `python sioux_falls.py --help` to change the insertion and simulated hours, the path threshold, the path update interval, the fraction of intelligent agents or the seed.

The network data are read from the `TransportationNetworks` submodule, so be sure to have it checked out (see the main README).
The map tiles are downloaded from Esri, so drawing them needs an internet connection: without it, the map is drawn without tiles.

## Motivation
Sioux Falls is the most used benchmark in traffic assignment: a small network with a known user-equilibrium (UE) solution.
The question is whether DSF gets close to the UE link flows starting from just the origin-destination matrix and agents routed on travel times, without calibrating anything.

## Setup
The TNTP files are translated into DSF inputs as follows:
- **Links**: the benchmark link lengths equal the free-flow times, so they are read as miles and minutes, i.e. 60 mph on every link. A DSF lane releases at most one vehicle per second, so the number of lanes is `ceil(capacity / 3600)`. Each link then gets a transport capacity of `capacity / (3600 * lanes)`: each lane releases its front vehicle with that probability per second, and the link carries exactly its benchmark capacity.
- **Zones**: every node is a zone, and paths may go through it. Each zone gets an origin edge from a centroid to its node and a destination edge from its node to another centroid, both wide enough for the zone's demand. Agents depart on the origin edge and arrive at the start of the destination edge, so that they are free to choose their first and last link.
- **Demand**: the OD matrix (360,600 trips) is hourly, but it does not fit within the link capacities in one hour. A maximum concurrent flow computation shows that, even with ideal routing, only 52% of it does: the UE solution loads links up to 2.5 times their capacity, which the BPR cost function allows. The demand is therefore inserted evenly over 2 hours (`--insertion-hours`), the shortest period over which it fits; afterwards the network is left to empty.
- **Routing**: every agent follows the paths computed on the current travel times (free-flow time plus queue delay), updated every 300 seconds. Paths within 5% of the best one are considered equivalent.

Every link traversal is counted over the whole run, so the simulated volume of a link is the number of trips using it, i.e. the same quantity as a static assignment volume.

## Results
All trips arrive within about 2.6 hours, with no gridlock.
The simulated link volumes follow the UE ones with Pearson r ≈ 0.963–0.969 and R² ≈ 0.925–0.937, and the total volume is within 0.5% of the UE one.
The ranges come from repeated runs: the results change slightly between runs even with the same seed.

The largest deviations have a pattern. Low-capacity links (≈ 5,000 veh/h), which the UE loads at 1.4–1.7 times their capacity, are overloaded by up to 30% (e.g. 22–20 and 11–12).
Lightly loaded high-capacity links (e.g. 1–2, 1–3, 3–12 and 7–18) are instead underloaded by 15–30%.
Since the link capacities are exact, the pattern does not come from the capacity mapping.
It probably comes from the cost of congestion: at 1.7 times its capacity, the BPR travel time of a link is 2.3 times its free-flow time, while in DSF the delay only grows with the queues.

### Map
`flows_map.pdf` draws every link over a map of the city, with the two directions of a link side by side and the line width growing with the UE volume.
Links are colored by their signed GEH, i.e. the GEH with the sign of the simulated minus the UE volume, on a stepped scale shared by all the toy models.
Links with |GEH| < 5 are gray, while blue (underestimated) and red (overestimated) links grow darker with the disagreement, in steps at 10, 20 and 30.
The node positions only approximate the real streets, since the benchmark network is a simplified model of the city.
The map shows the pattern above: the underestimated links are mostly high-capacity ones (median 18,700 veh/h) in the northern half, while the overestimated ones are mostly low-capacity links (median 5,100 veh/h) further south.

### Insertion period
Changing the insertion period with `--insertion-hours` gives (2–18 runs each):

| Insertion (h) | Pearson r | R² | Network empty after |
|---|---|---|---|
| 1 | 0.924–0.937 | 0.81–0.84 | ~3.3 h, gridlock in 3 of 18 runs |
| 1.5 | 0.971–0.973 | 0.931–0.937 | ~2.9 h |
| 1.75 | 0.973–0.976 | 0.939–0.947 | ~2.6 h |
| 2 | 0.963–0.969 | 0.925–0.937 | ~2.6 h |
| 2.5 | 0.917–0.918 | 0.831–0.835 | ~3.0 h |
| 3 | 0.816–0.824 | 0.636–0.651 | ~3.5 h |

Inserting the demand in one hour overloads the network: the queues shift the flows away from the UE ones, and sometimes block the network.
Longer periods keep the network below its capacity, so the flows drift towards the free-flow paths, while the UE is a congested state.
The best match is between 1.5 and 2 hours, around the 1.9 hours that the maximum concurrent flow requires.

### Fraction of intelligent agents
Only intelligent agents follow the updated paths: the others keep the free-flow ones.
Changing the fraction with `--intelligent-fraction` gives (3 runs each):

| Fraction | Pearson r | R² | Network empty after |
|---|---|---|---|
| 0.0 | 0.52 | < 0 | gridlock |
| 0.25 | 0.68 | 0.20–0.22 | ~7 h |
| 0.5 | 0.84–0.85 | 0.66–0.68 | ~4.7 h |
| 0.75 | 0.95 | 0.89–0.91 | ~3 h |
| 0.9 | 0.96 | 0.93 | ~2.6 h |
| 1.0 | 0.96–0.97 | 0.93–0.94 | ~2.6 h |

The flows get closer to the UE ones as more agents react to congestion, since free-flow paths overload the shortest routes.
Without rerouting, the network gridlocks: more than 170,000 agents are still stuck after 10 hours.

## Data
Network, demand, node coordinates and UE flows are taken from [TransportationNetworks](https://github.com/bstabler/TransportationNetworks/tree/master/SiouxFalls).
Map tiles are © Esri.
