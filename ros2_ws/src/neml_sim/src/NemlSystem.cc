// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// World system plugin behind the /world/<w>/neml/* services that
// mcp_servers/neml_mcp_sim/server.py calls (SPEC 11.1, 11.4). Every service is
// gz.msgs.StringMsg in / out, the payload is JSON in `data`.
//
//   policy     load a neml-linear-policy-v1 file, reply with its sha256
//   randomize  apply the SPEC 11.4 record (masses, torque gain, latency, noise)
//   run_until  state probe: condition check + sim_time_s (the caller steps)
//   metrics    success / violation + policy_sha256
//   capture    latest camera frame written to disk, reply with the path
//   shutdown   SIGINT
//
// With a policy loaded the plugin closes the loop itself: every kControlEvery
// iterations it builds the normalised feature vector, takes the argmax action
// of the LinearPolicy and publishes the matching Twist on /model/<ns>/cmd_vel.
// The action names map to fixed, bounded velocities, so a policy can only pick
// among plugin-approved moves (platform/policy.py); unknown names mean "stop".
//
// Verified on Gazebo Harmonic (gz-sim8, arm64, headless) with test_rover.sdf.
#include <gz/msgs/empty.pb.h>
#include <gz/msgs/image.pb.h>
#include <gz/msgs/stringmsg.pb.h>
#include <gz/msgs/twist.pb.h>
#include <openssl/evp.h>

#include <algorithm>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <fstream>
#include <map>
#include <mutex>
#include <nlohmann/json.hpp>
#include <random>
#include <sstream>

#include <gz/plugin/Register.hh>
#include <gz/sim/EntityComponentManager.hh>
#include <gz/sim/System.hh>
#include <gz/sim/components/Inertial.hh>
#include <gz/sim/components/Name.hh>
#include <gz/sim/components/Pose.hh>
#include <gz/sim/components/World.hh>
#include <gz/transport/Node.hh>

using json = nlohmann::json;

namespace neml {

constexpr int kControlEvery = 50;  // 20 Hz at the 1 ms world step
constexpr double kControlDt = kControlEvery * 0.001;

// sha256 of the bytes this process actually read, so get_metrics proves which
// policy ran (PhysicsRunner rejects a mismatch).
std::string Sha256Bytes(const std::string &bytes) {
  unsigned char md[EVP_MAX_MD_SIZE];
  unsigned int len = 0;
  EVP_Digest(bytes.data(), bytes.size(), md, &len, EVP_sha256(), nullptr);
  char hex[3];
  std::string out;
  for (unsigned int i = 0; i < len; ++i) {
    snprintf(hex, sizeof hex, "%02x", md[i]);
    out += hex;
  }
  return out;
}

std::string ReadFile(const std::string &path) {
  std::ifstream in(path, std::ios::binary);
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

double Clamp1(double v) { return std::max(-1.0, std::min(1.0, v)); }

struct Move {
  double lin, ang;
};
// The only velocities a policy can ever command (m/s, rad/s).
const std::map<std::string, Move> kMoves = {
    {"forward", {0.5, 0.0}},   {"backward", {-0.3, 0.0}},   {"turn_left", {0.0, 0.8}},
    {"turn_right", {0.0, -0.8}}, {"forward_left", {0.4, 0.4}}, {"forward_right", {0.4, -0.4}},
    {"stop", {0.0, 0.0}},
};

class NemlSystem : public gz::sim::System,
                   public gz::sim::ISystemConfigure,
                   public gz::sim::ISystemPreUpdate,
                   public gz::sim::ISystemPostUpdate {
 public:
  void Configure(const gz::sim::Entity &, const std::shared_ptr<const sdf::Element> &,
                 gz::sim::EntityComponentManager &ecm, gz::sim::EventManager &) override {
    this->ecm = &ecm;
    this->world = WorldName(ecm);
    const std::string w = "/world/" + this->world + "/neml/";
    this->node.Advertise(w + "policy", &NemlSystem::Policy, this);
    this->node.Advertise(w + "randomize", &NemlSystem::Randomize, this);
    this->node.Advertise(w + "run_until", &NemlSystem::RunUntil, this);
    this->node.Advertise(w + "metrics", &NemlSystem::Metrics, this);
    this->node.Advertise(w + "capture", &NemlSystem::Capture, this);
    this->node.Advertise(w + "shutdown", &NemlSystem::Shutdown, this);
  }

  void PreUpdate(const gz::sim::UpdateInfo &info, gz::sim::EntityComponentManager &) override {
    if (info.paused) return;
    std::lock_guard<std::mutex> g(this->mu);
    if (this->actions.empty() || this->ns.empty() || info.iterations % kControlEvery != 0) return;
    const std::string chosen = this->Choose(info);
    this->pending.push_back(chosen);
    if (static_cast<int>(this->pending.size()) <= this->latencyTicks) return;
    const std::string act = this->pending.front();
    this->pending.pop_front();
    auto it = kMoves.find(act);
    const Move m = it == kMoves.end() ? kMoves.at("stop") : it->second;
    gz::msgs::Twist t;
    t.mutable_linear()->set_x(m.lin * this->gain);
    t.mutable_angular()->set_z(m.ang * this->gain);
    if (!this->cmdPub) this->cmdPub = this->node.Advertise<gz::msgs::Twist>("/model/" + this->ns + "/cmd_vel");
    this->cmdPub.Publish(t);
    this->lastAction = act;
  }

  void PostUpdate(const gz::sim::UpdateInfo &info,
                  const gz::sim::EntityComponentManager &ecm) override {
    std::lock_guard<std::mutex> g(this->mu);
    this->simTime = std::chrono::duration<double>(info.simTime).count();
    // Success = the base reached goal_x_m; violation = it tipped over
    // (|roll| or |pitch| > 60 deg).
    ecm.Each<gz::sim::components::Name, gz::sim::components::Pose>(
        [&](const gz::sim::Entity &, const gz::sim::components::Name *n,
            const gz::sim::components::Pose *p) {
          if (n->Data() != this->ns) return true;
          const auto &pose = p->Data();
          this->x = pose.Pos().X();
          this->y = pose.Pos().Y();
          this->yaw = pose.Rot().Yaw();
          if (std::abs(pose.Rot().Roll()) > 1.047 || std::abs(pose.Rot().Pitch()) > 1.047)
            this->violation = 1.0;
          return true;
        });
  }

 private:
  static std::string WorldName(gz::sim::EntityComponentManager &ecm) {
    std::string name = "default";
    ecm.Each<gz::sim::components::Name, gz::sim::components::World>(
        [&](const gz::sim::Entity &, const gz::sim::components::Name *n,
            const gz::sim::components::World *) {
          name = n->Data();
          return false;
        });
    return name;
  }

  static bool Reply(gz::msgs::StringMsg &rep, const json &j) {
    rep.set_data(j.dump());
    return true;
  }

  double Noise(double sigma) {
    if (sigma <= 0) return 0.0;
    return std::normal_distribution<double>(0.0, sigma)(this->rng);
  }

  // Features in [-1,1] (LinearPolicy rejects anything else); extra slots stay 0.
  std::string Choose(const gz::sim::UpdateInfo &info) {
    const double goal = this->params.value("goal_x_m", 1.0);
    const double vx = (this->x - this->prevX) / kControlDt;
    this->prevX = this->x;
    const double base[] = {
        Clamp1((this->x + Noise(this->encNoise)) / goal),
        Clamp1(this->y + Noise(this->encNoise)),
        Clamp1((this->yaw + Noise(this->imuNoise)) / M_PI),
        Clamp1(vx),
        Clamp1(std::chrono::duration<double>(info.simTime).count() / 60.0),
    };
    std::string best = "stop";
    double bestScore = -1e300;
    for (const auto &a : this->actions) {
      const auto &w = this->weights[a];
      double s = 0;
      for (size_t i = 0; i < w.size(); ++i) s += (i < 5 ? base[i] : 0.0) * w[i];
      if (s > bestScore) {  // first maximum wins, same tie-break as max() in Python
        bestScore = s;
        best = a;
      }
    }
    return best;
  }

  bool Policy(const gz::msgs::StringMsg &req, gz::msgs::StringMsg &rep) {
    auto j = json::parse(req.data(), nullptr, false);
    if (j.is_discarded()) return Reply(rep, {{"error", "bad json"}});
    const std::string bytes = ReadFile(j.value("path", ""));
    if (bytes.empty()) return Reply(rep, {{"error", "policy file unreadable"}});
    auto p = json::parse(bytes, nullptr, false);
    std::lock_guard<std::mutex> g(this->mu);
    this->policySha = Sha256Bytes(bytes);
    this->actions.clear();
    this->weights.clear();
    if (!p.is_discarded() && p.value("format", "") == "neml-linear-policy-v1") {
      for (const auto &a : p["actions"]) {
        this->actions.push_back(a.get<std::string>());
        this->weights[this->actions.back()] = p["weights"][this->actions.back()].get<std::vector<double>>();
      }
    }
    this->ns = j.value("ns", this->ns);
    return Reply(rep, {{"policy_sha256", this->policySha}, {"actions", this->actions.size()}});
  }

  bool Randomize(const gz::msgs::StringMsg &req, gz::msgs::StringMsg &rep) {
    auto j = json::parse(req.data(), nullptr, false);
    if (j.is_discarded()) return Reply(rep, {{"error", "bad json"}});
    std::lock_guard<std::mutex> g(this->mu);
    this->ns = j.value("ns", "");
    this->violation = 0.0;
    this->prevX = 0.0;
    this->pending.clear();
    this->rng.seed(static_cast<unsigned>(j.value("seed", 0)));
    this->gain = j.value("motor_torque_constant", 1.0);
    this->latencyTicks = static_cast<int>(std::lround(j.value("control_latency_s", 0.0) / kControlDt));
    this->imuNoise = j.value("imu_noise_sigma_rads", 0.0);
    this->encNoise = j.value("encoder_noise_sigma_rad", 0.0);
    int massesSet = 0;
    if (j.contains("link_masses_kg")) {
      for (auto &[link, kg] : j["link_masses_kg"].items()) {
        this->ecm->Each<gz::sim::components::Name, gz::sim::components::Inertial>(
            [&](const gz::sim::Entity &e, const gz::sim::components::Name *n,
                const gz::sim::components::Inertial *in) {
              if (n->Data() != link) return true;
              auto inertial = in->Data();
              auto m = inertial.MassMatrix();
              m.SetMass(kg.get<double>());
              inertial.SetMassMatrix(m);
              this->ecm->SetComponentData<gz::sim::components::Inertial>(e, inertial);
              this->ecm->SetChanged(e, gz::sim::components::Inertial::typeId,
                                    gz::sim::ComponentState::OneTimeChange);
              ++massesSet;
              return true;
            });
      }
    }
    this->params = j;
    return Reply(rep, {{"applied", true}, {"masses_set", massesSet}, {"latency_ticks", this->latencyTicks}});
  }

  // Conditions are the two forms the brain emits: `sim_time_s>=T` and `x>=X`.
  // The state is read at call time; the caller owns the stepping.
  bool RunUntil(const gz::msgs::StringMsg &req, gz::msgs::StringMsg &rep) {
    auto j = json::parse(req.data(), nullptr, false);
    if (j.is_discarded()) return Reply(rep, {{"error", "bad json"}});
    const std::string cond = j.value("condition", "");
    std::lock_guard<std::mutex> g(this->mu);
    const auto pos = cond.find(">=");
    bool ok = false;
    if (pos != std::string::npos) {
      const std::string key = cond.substr(0, pos);
      const double v = std::atof(cond.c_str() + pos + 2);
      ok = (key == "sim_time_s" ? this->simTime : key == "x" ? this->x : -1e300) >= v;
    }
    return Reply(rep, {{"satisfied", ok}, {"sim_time_s", this->simTime}});
  }

  bool Metrics(const gz::msgs::StringMsg &, gz::msgs::StringMsg &rep) {
    std::lock_guard<std::mutex> g(this->mu);
    const double goal = this->params.value("goal_x_m", 1.0);
    const double reached = this->x >= goal ? 1.0 : 0.0;
    // reality_gap needs a real-robot reference run; until one exists it is 0.
    json out = {{"values", {{"success_rate", reached * (1.0 - this->violation)},
                            {"reality_gap", this->params.value("reality_gap", 0.0)},
                            {"safety_violation", this->violation},
                            {"x_m", this->x},
                            {"y_m", this->y}}},
                {"policy_sha256", this->policySha},
                {"last_action", this->lastAction}};
    return Reply(rep, out);
  }

  // SPEC 6.3: frames leave as a path, never as bytes. The first request for a
  // camera subscribes and answers "no_frame"; the caller steps and retries.
  bool Capture(const gz::msgs::StringMsg &req, gz::msgs::StringMsg &rep) {
    auto j = json::parse(req.data(), nullptr, false);
    if (j.is_discarded()) return Reply(rep, {{"error", "bad json"}});
    const std::string cam = j.value("camera", "cam");
    const std::string nsName = j.value("ns", this->ns);
    std::lock_guard<std::mutex> g(this->mu);
    if (!this->subscribed.count(cam)) {
      const std::string topic =
          "/world/" + this->world + "/model/" + nsName + "/link/base_link/sensor/" + cam + "/image";
      this->subscribed[cam] = true;
      this->node.Subscribe<gz::msgs::Image>(
          topic, std::function<void(const gz::msgs::Image &)>([this, cam](const gz::msgs::Image &m) {
            std::lock_guard<std::mutex> g2(this->mu);
            this->frames[cam] = m;
          }));
    }
    auto it = this->frames.find(cam);
    if (it == this->frames.end()) return Reply(rep, {{"error", "no_frame"}});
    const auto &img = it->second;
    const char *dir = std::getenv("NEML_FRAME_DIR");
    const std::string d = dir ? dir : "/tmp/neml_frames";
    std::string mk = "mkdir -p '" + d + "'";
    if (std::system(mk.c_str()) != 0) return Reply(rep, {{"error", "cannot create frame dir"}});
    const std::string path = d + "/" + nsName + "_" + cam + ".ppm";
    std::ofstream out(path, std::ios::binary);
    out << "P6\n" << img.width() << " " << img.height() << "\n255\n" << img.data();
    return Reply(rep, {{"path", path}, {"width_px", img.width()}, {"height_px", img.height()},
                       {"encoding", "ppm"}});
  }

  bool Shutdown(const gz::msgs::StringMsg &, gz::msgs::StringMsg &rep) {
    Reply(rep, {{"ok", true}});
    std::raise(SIGINT);  // gz sim exits on SIGINT
    return true;
  }

  gz::transport::Node node;
  gz::transport::Node::Publisher cmdPub;
  gz::sim::EntityComponentManager *ecm{nullptr};
  std::mutex mu;
  std::string world, ns, policySha, lastAction;
  json params = json::object();
  std::vector<std::string> actions;
  std::map<std::string, std::vector<double>> weights;
  std::deque<std::string> pending;
  std::map<std::string, bool> subscribed;
  std::map<std::string, gz::msgs::Image> frames;
  std::mt19937 rng{0};
  double simTime{0}, x{0}, y{0}, yaw{0}, prevX{0}, violation{0};
  double gain{1.0}, imuNoise{0}, encNoise{0};
  int latencyTicks{0};
};

}  // namespace neml

GZ_ADD_PLUGIN(neml::NemlSystem, gz::sim::System, neml::NemlSystem::ISystemConfigure,
              neml::NemlSystem::ISystemPreUpdate, neml::NemlSystem::ISystemPostUpdate)
GZ_ADD_PLUGIN_ALIAS(neml::NemlSystem, "neml::NemlSystem")
