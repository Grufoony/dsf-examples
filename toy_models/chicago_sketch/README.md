# Chicago sketch
To run the simulation, with `dsf-suite` >= 7.3.1:
```shell
python chicago_sketch.py
```

This will create a new `output` folder with the generated DSF inputs, the simulation data, the table `flows_comparison.csv`, the plot `flows_comparison.pdf` and the map `flows_map.pdf` (also as `flows_map.png`).
Run `python chicago_sketch.py --help` to change the insertion and simulated hours, the path threshold, the path update interval, the fraction of intelligent agents or the seed.
A run takes about 20 seconds.

The network data are read from the `TransportationNetworks` submodule, so be sure to have it checked out (see the main README).
The map tiles are downloaded from Esri, so drawing them needs an internet connection: without it, the map is drawn without tiles.

## Motivation
After [Sioux Falls](../sioux_falls/README.md) and [Anaheim](../anaheim/README.md), the Chicago sketch network is a step up in size: an aggregated model of the Chicago region with 933 nodes, 2,950 links, 387 zones and about 1.14 million trips, with a best-known user-equilibrium (UE) solution.
The question is the same: does DSF get close to the UE link flows starting from just the origin-destination matrix and agents routed on travel times, without calibrating anything?

## Setup
The TNTP files are translated into DSF inputs as follows:
- **Links**: lengths are in miles, and the speed limit of each link is its length over its free-flow time. A DSF lane releases at most one vehicle per second, so the number of lanes is `ceil(capacity / 3600)`. Each link then gets a transport capacity of `capacity / (3600 * lanes)`: each lane releases its front vehicle with that probability per second, and the link carries exactly its benchmark capacity.
- **Connectors**: the 774 zone connectors have a zero free-flow time, which DSF cannot represent. They become 50 m links at 50 km/h, crossed in about 4 seconds.
- **Zones**: the network file marks every node as a through node, but the UE solution sends no traffic through the zones. Each zone node therefore keeps its outgoing links, while its ingoing links end in a separate sink node, so that no path can cross a zone. Agents depart on an origin edge leading to the zone node and arrive at the start of a destination edge leaving the sink node, both wide enough for the zone's demand.
- **Demand**: the OD matrix has 1,137,493 trips between different zones (intrazonal trips are dropped), read as hourly. It is inserted evenly during the first hour (`--insertion-hours`); afterwards the network is left to empty.
- **Routing**: every agent follows the paths computed on the current travel times (free-flow time plus queue delay), updated every 300 seconds. Paths within 5% of the best one are considered equivalent.

Every link traversal is counted over the whole run, so the simulated volume of a link is the number of trips using it, i.e. the same quantity as a static assignment volume.

The benchmark UE minimizes a generalized cost that adds 0.04 minutes per mile to the travel times, while DSF routes on travel times only.
The difference is negligible: solving the UE again with travel times only gives the same link flows (R² = 0.9999, largest difference 346 vehicles), so the published solution is a fair reference.

## Results
The network holds up to about 400,000 agents at the end of the insertion hour. All trips arrive within about 4 hours, with no gridlock.
The simulated link volumes follow the UE ones with Pearson r ≈ 0.987 and R² ≈ 0.974, and the total volume is 2% above the UE one.
About 68% of the links have a GEH below 5.
The values come from repeated runs: the results change slightly between runs even with the same seed.

### Map
`flows_map.pdf` draws every link over a map of the region, with the two directions of a link side by side and the line width growing with the UE volume.
Links are colored by their signed GEH, i.e. the GEH with the sign of the simulated minus the UE volume, on a stepped scale shared by all the toy models.
Links with |GEH| < 5 are gray, while blue (underestimated) and red (overestimated) links grow darker with the disagreement, in steps at 10, 20 and 30.
The node coordinates are in the Illinois State Plane East system (NAD27, feet), which puts the network in place over the map tiles.
The errors concentrate in the dense central grid, where many parallel routes have similar costs, while most suburban and outer links are within the GEH threshold.
Overestimated links (about 610) outnumber underestimated ones (about 350), in line with the total volume being 2% above the UE one.

### Insertion period
Changing the insertion period with `--insertion-hours` gives (3 runs each):

| Insertion (h) | Pearson r | R² | Network empty after |
|---|---|---|---|
| 1 | 0.987 | 0.974 | ~4.1 h |
| 1.25 | 0.989 | 0.976 | ~4.1 h |
| 1.5 | 0.986–0.987 | 0.970–0.971 | ~4.1 h |
| 1.75 | 0.982 | 0.958–0.959 | ~4.3 h |
| 2 | 0.975 | 0.941–0.942 | ~4.5 h |
| 2.5 | 0.963 | 0.910 | ~5 h |
| 3 | 0.953 | 0.882–0.883 | ~5.4 h |
| 4 | 0.939–0.940 | 0.843–0.847 | ~6.4 h |

Unlike Sioux Falls and Anaheim, the network carries the hourly demand in about one hour, and longer insertion periods only move the flows away from the congested UE state.
A maximum concurrent flow computation says that only 42% of the demand fits within the link capacities, but a single link sets that limit: the only access to zone 37 (540 → 583) must carry 7,137 trips with a capacity of 3,000 veh/h.
Its queue is the last one to clear, about 2.5 hours into the run. After 3 hours no link has a queue left, and the last agents are only completing long regional trips.

### Path threshold
Paths within the threshold of the best one are all used, while the UE only uses paths of exactly minimum cost.
Changing the threshold with `--threshold` gives (3 runs each):

| Threshold | Pearson r | R² | Links with GEH < 5 |
|---|---|---|---|
| 0.0 | 0.988–0.989 | 0.976–0.977 | 72–73% |
| 0.02 | 0.988–0.989 | 0.976 | 71–72% |
| 0.05 | 0.987 | 0.973–0.974 | 67–68% |
| 0.1 | 0.984 | 0.966–0.967 | 61–62% |

The default is kept at 0.05, as for the other models, so that they are comparable.

### Fraction of intelligent agents
Only intelligent agents follow the updated paths: the others keep the free-flow ones.
Changing the fraction with `--intelligent-fraction` gives (3 runs each):

| Fraction | Pearson r | R² | Network empty after |
|---|---|---|---|
| 0.0 | 0.899–0.901 | 0.746–0.751 | gridlock |
| 0.25 | 0.956–0.957 | 0.892–0.894 | ~2,000 agents stuck after 10 h |
| 0.5 | 0.981 | 0.956 | 31–107 agents left after 8 h |
| 0.75 | 0.986 | 0.970–0.971 | ~5.8 h |
| 0.9 | 0.987 | 0.972 | ~4 h |
| 1.0 | 0.987 | 0.973–0.974 | ~4 h |

Without rerouting the network gridlocks, with 55,000–61,000 agents still stuck after 10 hours.
Most of the fit is recovered with half of the agents rerouting, but the network only empties when most of them do.

## Data
Network, demand, node coordinates and UE flows are taken from [TransportationNetworks](https://github.com/bstabler/TransportationNetworks/tree/master/Chicago-Sketch).
Map tiles are © Esri.
