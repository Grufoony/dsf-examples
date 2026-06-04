#include <dsf/dsf.hpp>
#include <array>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <random>
#include <string>

using Delay = uint8_t;

using namespace dsf::mobility;

int main(int argc, char* argv[]) {
  auto constexpr MAX_TIME{static_cast<std::time_t>(75e3)};
  // Get N_MAX from command line arguments, default to 10
  if (argc < 3) {
    std::cerr << "Usage: " << argv[0] << " N_MAX SEED ALPHA\n";
    return 1;
  }
  std::size_t const N_MAX = std::stoul(argv[1]);
  std::size_t const SEED = std::stoul(argv[2]);
  // double const alpha = std::stod(argv[3]);
  // double const beta = std::stod(argv[4]);

  for (std::size_t N_TRAFFICLIGHTS = 1; N_TRAFFICLIGHTS <= N_MAX; ++N_TRAFFICLIGHTS) {
    double alpha = 0.1;
    std::cout << std::format("Simulating with {} traffic lights...\n", N_TRAFFICLIGHTS);
    auto generator = std::mt19937{std::random_device{}()};
    generator.seed(SEED);
    std::normal_distribution<double> lengthDist{60., 10.};
    auto const length = lengthDist(generator);
    std::uniform_int_distribution<> phaseDist{0, static_cast<int>(length * 2)};
    std::uniform_real_distribution<> probDist{0., 1.};
    // Create the graph
    RoadNetwork graph;

    for (dsf::Id id{0}; id < N_TRAFFICLIGHTS + 1; ++id) {
      Street s{id, std::make_pair(id, id + 1), 600., 13.9, 2};
      graph.addStreets(s);
    }
    for (dsf::Id id{0}; id < N_TRAFFICLIGHTS; ++id) {
      graph.makeTrafficLight(id + 1);
      auto& tl = graph.node<TrafficLight>(id + 1);
      auto& street = graph.edge(id);
      tl.addPhase(TrafficLightPhase{static_cast<Delay>(length),
                                    {{street.id(), {dsf::Direction::ANY}}}});
      tl.addPhase(TrafficLightPhase{static_cast<Delay>(length)});
      tl.advanceBy(phaseDist(generator));
      if (N_TRAFFICLIGHTS == N_MAX) {
        std::ofstream ofs_temp{std::format("./traffic_light_settings_{}.log", SEED),
                               std::ios::app};
        ofs_temp << std::format("{}\n", tl);
      }
    }
    graph.adjustNodeCapacities();
    graph.addCoil(N_TRAFFICLIGHTS);
    auto& outputCoil = graph.edge(N_TRAFFICLIGHTS);

    // Create the dynamics
    FirstOrderDynamics dynamics{std::move(graph), false, SEED};
    dynamics.setODs({{0, N_TRAFFICLIGHTS + 1, 1.}});
    dynamics.updatePaths();

    // Evolution
    std::ofstream ofs{
        std::format("./{}_traffic_light_output_{}.csv", SEED, N_TRAFFICLIGHTS)};
    // print two columns, time and vehicles
    ofs << "time;input_flow;output_flow\n";
    std::size_t totAgents{0};
    for (std::time_t progress{0}; progress <= MAX_TIME; ++progress) {
      if (progress > 0 && progress % 300 == 0) {
        ofs << progress << ';' << totAgents << ';' << outputCoil.counts() << std::endl;
        totAgents = 0;
        outputCoil.resetCounter();
      }
      // if (progress % 2 == 0) {
      //   dynamics.addAgents(1, AgentInsertionMethod::ODS);
      //   ++totAgents;
      //   if (progress > 5000 && progress % 5 == 0) {
      //       dynamics.addAgents(1, AgentInsertionMethod::ODS);
      //       ++totAgents;
      //   }
      //   if (progress > 10000 && progress % 4 == 0) {
      //       dynamics.addAgents(1, AgentInsertionMethod::ODS);
      //       ++totAgents;
      //   }
      //   if (progress > 15000 && progress % 3 == 0) {
      //       dynamics.addAgents(1, AgentInsertionMethod::ODS);
      //       ++totAgents;
      //   }
      // }
      if (probDist(generator) < alpha) {
        dynamics.addAgents(1, AgentInsertionMethod::ODS);
        ++totAgents;
      }
      if (progress > 0 && progress % 5000 == 0) {
        alpha += 0.1;
        std::cout << std::format("Time: {}, alpha: {}\n", progress, alpha);
      }
      dynamics.evolve();
    }
  }

  return 0;
}