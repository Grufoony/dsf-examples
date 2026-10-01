# Anaheim
To run the simulation, with `dsf-suite` >= 7.3.1:
```shell
python anaheim.py
```

This will create a new `output` folder with the generated DSF inputs, the simulation data, the table `flows_comparison.csv`, the plot `flows_comparison.pdf` and the map `flows_map.pdf` (also as `flows_map.png`).
Run `python anaheim.py --help` to change the insertion and simulated hours, the path threshold, the path update interval, the fraction of intelligent agents or the seed.
A run takes a few seconds.

The network data are read from the `TransportationNetworks` submodule, so be sure to have it checked out (see the main README).
The map tiles are downloaded from Esri, so drawing them needs an internet connection: without it, the map is drawn without tiles.

## Motivation
After [Sioux Falls](../sioux_falls/README.md), Anaheim is the next step: a real city network (1992) of 416 nodes and 914 links, with a best-known user-equilibrium (UE) solution.
The question is the same: does DSF get close to the UE link flows starting from just the origin-destination matrix and agents routed on travel times, without calibrating anything?

## Setup
The TNTP files are translated into DSF inputs as follows:
- **Links**: lengths are converted from feet, and the speed limit of each link is its length over its free-flow time. Benchmark capacities are all multiples of 1800 veh/h, the capacity of one lane, so the number of lanes is `capacity / 1800`. A DSF lane releases at most one vehicle per second, so every link gets a transport capacity of 0.5: each lane then releases its front vehicle with probability 0.5 per second, and the link carries exactly its benchmark capacity.
- **Zones**: zones 1–38 are not through nodes. Each zone node keeps its outgoing links, while its ingoing links end in a separate sink node, so that no path can cross a zone. Agents depart on an origin edge leading to the zone node and arrive at the start of a destination edge leaving the sink node, both wide enough for the zone's demand. They are then free to choose their first and last link.
- **Demand**: the OD matrix (104,694 trips) is hourly, but it does not fit within the link capacities in one hour. A maximum concurrent flow computation shows that, even with ideal routing, only 53% of it does. The bottleneck is zone 2, whose only access link (63 → 62) must carry 13,602 trips with a capacity of 7,200 veh/h. The demand is therefore inserted evenly over 2 hours (`--insertion-hours`), the shortest period over which it fits; afterwards the network is left to empty.
- **Routing**: every agent follows the paths computed on the current travel times (free-flow time plus queue delay), updated every 300 seconds. Paths within 5% of the best one are considered equivalent.

Every link traversal is counted over the whole run, so the simulated volume of a link is the number of trips using it, i.e. the same quantity as a static assignment volume.

## Results
All trips arrive within about 3.1 hours, with no gridlock. The last hour only serves the queue on the access link of zone 2.
The simulated link volumes follow the UE ones with Pearson r ≈ 0.993 and R² ≈ 0.987, and the total volume is within 1% of the UE one.
About 62% of the links have a GEH below 5.
The values come from repeated runs: the results change slightly between runs even with the same seed.

The fit is better than on Sioux Falls because Anaheim is less congested: the median UE volume / capacity ratio is 0.16, and only 63 links are above 1.
Links above half of their capacity have a median absolute error of about 3%, while the lightly loaded links reach 10%.

The largest deviations come from near-equivalent routes on lightly loaded links. For example, the UE sends 551 vehicles along 269 → 270 → 271, while the simulation sends 1,785.

### Map
`flows_map.pdf` draws every link over a map of the city, with the two directions of a link side by side and the line width growing with the UE volume.
Links are colored by their signed GEH, i.e. the GEH with the sign of the simulated minus the UE volume, on a stepped scale shared by all the toy models.
Links with |GEH| < 5 are gray, while blue (underestimated) and red (overestimated) links grow darker with the disagreement, in steps at 10, 20 and 30.
Most freeway links are gray, while the errors are spread over the arterial grid, where many parallel routes have similar costs.

### Insertion period
Changing the insertion period with `--insertion-hours` gives (2–5 runs each):

| Insertion (h) | Pearson r | R² | Network empty after |
|---|---|---|---|
| 1 | 0.973–0.975 | 0.940–0.943 | ~3.1 h |
| 1.25 | 0.980–0.981 | 0.956–0.958 | ~3.1 h |
| 1.5 | 0.987–0.988 | 0.973 | ~3.1 h |
| 2 | 0.993–0.994 | 0.986–0.988 | ~3.1 h |
| 2.5 | 0.991–0.992 | 0.982 | ~3.1 h |
| 3 | 0.991 | 0.979–0.980 | ~3.5 h |
| 4 | 0.990 | 0.978 | ~4.5 h |

Shorter periods overload the network, and the queues shift the flows away from the UE ones.
Longer periods keep the network below its capacity, so the flows drift towards the free-flow paths, while the UE is a congested state.

### Path threshold
Paths within the threshold of the best one are all used, while the UE only uses paths of exactly minimum cost.
Changing the threshold with `--threshold` gives (3 runs each):

| Threshold | Pearson r | R² | Links with GEH < 5 |
|---|---|---|---|
| 0.0 | 0.997 | 0.994–0.995 | 78–79% |
| 0.01 | 0.997–0.998 | 0.994–0.995 | 77–78% |
| 0.02 | 0.996–0.997 | 0.993 | 73–74% |
| 0.05 | 0.993 | 0.987 | 61–63% |
| 0.1 | 0.990 | 0.979–0.980 | 54–56% |

The default is kept at 0.05, as for Sioux Falls, so that the two models are comparable.

### Fraction of intelligent agents
Only intelligent agents follow the updated paths: the others keep the free-flow ones.
Changing the fraction with `--intelligent-fraction` gives (3 runs each):

| Fraction | Pearson r | R² |
|---|---|---|
| 0.0 | 0.987 | 0.970–0.971 |
| 0.25 | 0.991 | 0.980 |
| 0.5 | 0.992 | 0.983–0.984 |
| 0.75 | 0.993 | 0.986 |
| 0.9 | 0.993–0.994 | 0.986–0.987 |
| 1.0 | 0.993 | 0.987 |

The network empties after about 3.1 hours whatever the fraction, since the access link of zone 2 cannot be avoided.
Even free-flow routing gets close to the UE flows, because of the low congestion: rerouting adds the last percent.

## Data
Network, demand, node coordinates and UE flows are taken from [TransportationNetworks](https://github.com/bstabler/TransportationNetworks/tree/master/Anaheim).
Map tiles are © Esri.
