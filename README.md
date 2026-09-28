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
