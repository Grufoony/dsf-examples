# dsf-examples

Usage examples for the DynamicalSystemFramework.

## Getting Started
This project uses `uv`. To install requierements:
```shell
uv sync
```
Then select the auto-created virtual environment to run notebooks.

The toy models rely on data stored in git submodules. Clone with `--recursive` or fetch them with:
```shell
git submodule update --init --recursive
```

## Toy models
The `toy_models` folder tests the simulator on standard benchmark networks from [TransportationNetworks](https://github.com/bstabler/TransportationNetworks):
- [Sioux Falls](toy_models/sioux_falls/README.md): simulated link flows compared with the user-equilibrium flows of the benchmark.
- [Anaheim](toy_models/anaheim/README.md): the same comparison on a real city network, with zones that cannot be crossed.
- [Chicago sketch](toy_models/chicago_sketch/README.md): the same comparison on a regional network of about 3,000 links and 1.1 million trips.

Each model also maps its link errors over real map tiles. The code they share (TNTP readers, DSF inputs, simulation, comparison, map and command-line options) lives in [toy_models/utils.py](toy_models/utils.py).
