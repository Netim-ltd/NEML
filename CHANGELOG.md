<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Değişiklik Günlüğü

Bu dosyanın biçimi [Keep a Changelog 1.1.0](https://keepachangelog.com/tr/1.1.0/)
esas alır ve proje [Semantic Versioning](https://semver.org/lang/tr/) kullanır.

> Bu dosya ağaçtaki gerçeği anlatır. Bir görev burada "Eklendi" altında
> yazıyorsa karşılığı depoda vardır; olmayan bir şey "Bilinen boşluklar"
> altında açıkça yazılır (NEML_SPEC.md §0.2: hiçbir alan "TBD" değildir).

## [Yayımlanmadı]

### Faz 0 — Temel (NEML_SPEC.md §16, T-001…T-007)

#### Eklendi
- Düzeltildi (gerçek araçlarla bulundu): FreeCAD kütle özellikleri ve sürücü argv; KiCad şematik sembol adları, pin etiketi yönü ve DRC/ERC sonuç yorumu; Blender imajında eksik GL kütüphaneleri; `GazeboPhysicsRunner` sürtünme kopyasında göreli mesh yolları.
- Eklendi: `test_tool_integration.py`, Blender `NEML_RENDER_PERCENT` / `NEML_RENDER_FRAME_STEP`.
- Dağıtım: `deploy/vps/compose.yml` (GPU'suz tam yığın, llama.cpp), `docker/sim`, `docker/cad`, `neml_brain/paths.py`, `LlamaCppProvider`, MCP argüman uyarlayıcı, `psycopg[binary]`.
- Düzeltildi (canlı yığında bulundu): komut hattının çökmesi (libpq, `untrusted()` sarmalayıcısı), router etiket açıklamaları, llama.cpp sayı sınırları, uydurma `task_id`, `priority` aralığı, CAD zorunlu alanları.
- Gazebo: `NemlSystem` dünya eklentisi (policy/randomize/run_until/metrics/capture/shutdown), politika yürütme, `test_rover.sdf`, gerçek-Gazebo entegrasyon testleri, `PooledPhysicsRunner`, `reality_gap` referansı.
- Düzeltildi: `GzRunner` kalıcı duraklı `gz sim` süreci kullanır; `GazeboPhysicsRunner` pose anahtarları; ROS paketleri arası döngüsel test bağımlılığı.

- **T-001 Repo iskeleti.** `LICENSE` (§1.2), `SAFETY.md` (§5), `README.md`,
  `.gitignore`, git-lfs izlemesi (`*.stl *.step *.3mf *.gcode *.png *.mp4
  *.bag *.FCStd`, §15) ve `.pre-commit-config.yaml` — telif başlığı kontrolü,
  GPL/AGPL tarama (§1.3), ruff, ruff-format, mypy --strict (brain/), bandit,
  gitleaks (§0.8, §18.2).
- **Konfigürasyon.** `config/llm.yaml` (§4.2/§4.4/§4.7),
  `config/mcp.yaml` (§6.5), `config/budget.yaml` (§14.4),
  `config/gz_bridge.yaml` (§11.1/§17.2), `config/policy/tools.yaml` (§5.4),
  `config/profiles/sim_{fast,lidar,visual}.yaml` (§4.5).
- **`.env.example`** — §17.3'teki tüm ortam değişkenleri, `CHANGEME`
  yer tutucularıyla.
- **`docs/adr/`** — ADR-001…ADR-008: Isaac Sim'in kullanılmaması, Qdrant
  yerine pgvector, tek LLM runtime olarak vLLM, 3 GB VRAM kısıtının mimariyi
  belirlemesi, kısıtlı üretim mimarisi, NAT için outbound-only bridge,
  `rmw_zenoh_cpp` seçimi, GPL/AGPL izolasyonu.
- **`docs/runbooks/`** — e-stop tetiklenmesi, reality gap aşımı, bütçe aşımı,
  bridge kopması, GPU mutex kilitlenmesi, başarısız baskı.
- **T-002 Kurulum betikleri.** `scripts/setup/01_system.sh` … `05_mcp_servers.sh`
  — Ubuntu 24.04 + ROS 2 Jazzy + Gazebo Harmonic + FreeCAD/KiCad/PrusaSlicer
  + MCP sunucuları (§17.4 sırasıyla).
- **T-003 Veritabanı.** `docker/postgres/init.sql` (pgvector), §7 şeması ve
  `brain/alembic/versions/0001_initial.py`, `0002_weights_lock.py`
  (kampanya ağırlık kilidi, §14.3); `scripts/db/` bölümleme ve seed.
- **T-004 Docker compose.** `docker/compose.yml` + `docker/brain/Dockerfile`,
  `docker/sandbox/Dockerfile` (§5.3 ağsız sandbox imajı).
- **T-005 vLLM.** `docker/vllm/README.md` — 3 GB VRAM profili ve model indirme
  (§4.2).
- **T-006 Gömme servisi.** `docker/embed/` — 384 boyutlu CPU ONNX servisi,
  `test_embed.py` ile sözleşme testleri (§4.6).
- **T-007 CI.** `.github/workflows/ci.yml` — §18.2'deki dokuz kapı, artı
  firmware host testleri ve `release.yml`.

### Faz 1 — Beyin (T-010…T-020)

#### Eklendi

- **`brain/neml_brain/`** — FastAPI + LangGraph beyin paketi (§8.2):
  `llm/` (LLMProvider + vLLM, guided_choice/guided_json, §4.3/§4.7),
  `agents/` (orchestrator, planner, coding, memory, §4.4),
  `safety/` (politika motoru ve onay kapıları, §5.2/§5.4),
  `runtime/` (sandbox §5.3, GPU mutex §4.5, bütçe §14.4, audit §18.3),
  `mcp/` (deterministik MCP istemcisi — modele araç listesi verilmez, §6.5),
  `api/` (§8.3 REST), `db/`, `memory/`, `bridge/` (§9.5 outbound-only),
  `generators/` (mech, urdf, dfm, elec, behavior — §12/§13),
  `evolution/` (fitness, seçilim, operatörler, reality gap — §14.3),
  `autonomy/` (döngü, görev keşfi, boşta kalma, öğrenme — §14),
  `cli/` (T-020 `nemlctl`).
- **`mcp_servers/`** — §6.2'deki dört sunucu: `neml_mcp_sim` (deterministik
  seed + GPU mutex), `neml_mcp_fab` (PrusaSlicer/PrusaLink, AGPL alt süreç
  sınırı), `neml_mcp_genome`, `neml_mcp_cad`; `mcp_servers/tests/` ile
  birlikte (§0.9).

### Faz 2 — Simülasyon (T-030…T-038)

#### Eklendi

- **`ros2_ws/src/`** — `neml_msgs`, `neml_description` (URDF/xacro),
  `neml_bringup`, `neml_control`, `neml_safety`, `neml_perception`,
  `neml_swarm`, `neml_sim` (dünyalar + `ros_gz` köprü konfigürasyonu).
- **`hardware/genome/`** — §13.3 genome şeması + `quadruped_v2.yaml`;
  `limits` bloğu koda gömülü olarak kilitli.
- **`manufacturing/slicer_profiles/`** — §12.3 DFM sınırlarına karşı test
  edilen dört dilimleyici profili.
- **`evolution/`** — fitness ağırlıkları, ağırlık şeması, arama operatörleri,
  `experiments/campaign_003/`.

### Faz 3 — Uzak API + Mobil (T-050…T-063)

#### Eklendi

- **`dotnet/`** — beş projeli `Neml.sln`: `Neml.Api` (§9.3 REST + §9.4
  SignalR), `Neml.Domain`, `Neml.Infrastructure`, `Neml.Web` (Blazor),
  `Neml.Cli`, `Neml.Tests` (endpoint sözleşme testleri).
- **`mobile/`** — Flutter uygulaması, §10.2'deki 13 ekran, §10.3 çevrimdışı
  yazma engeli ve TR/EN yerelleştirme.

### Faz 4 — Gerçek Robot (T-071…T-076)

#### Eklendi

- **`firmware/`** — `safety_watchdog` (ATmega328P, §5.1 L0 bağımsız koruma),
  `stm32_motion` (1 kHz, micro-ROS), `esp32_aux` (telemetri). Üçünün de host
  testi vardır ve CI'da koşar; `flash` hedefi yalnızca insana açıktır (§5.4).
- **`scripts/calibration/`** — §11.3 kalibrasyon manevraları ve testleri.
- **`scripts/release/`** — §0.6 sürüm damgalama ve artefakt manifestosu.

#### Eklendi (devam)

- `GET /v1/campaigns`, `GET /v1/tasks/{id}`, `GET /v1/approvals/{id}`; `nemlctl`
  artık listeyi süzmek yerine doğrudan okur.
- `POST /v1/sim/run` isteğine `physics` (§11.3) eklendi; neml-mcp-sim bunu
  `spawn_robot`'ta uygular ve `sim_version`'a katar. T-077 `fit` engeli kalktı.

- **Otonomi servisi** (`neml_brain.autonomy`): sonuç yargıcı, günlük gözden geçirme,
  kendini ayarlama, `docker/compose.autonomy.yml` ve `deploy/systemd/neml-autonomy.service`.
  Yalnızca simülasyon, varsayılan kapalı (ADR-014).
- **Köprü:** beyin artık bulutun `command` mesajlarını uygular ve `command_ack` döner,
  bekleyen onayları duyurur, canlı akışı gönderir. Daha önce yalnızca logluyordu.
- **Yönetici ekranı:** model başına zorunlu/önerilen alanlar (`/api/v1/model-settings`,
  Flutter Ayarlar → Robot modeli ayarları).
- `neml-mcp-fetch` (9109), `nemlctl robot safety-check`, BMS arıza hattı (`J30/J31/R9`),
  `scripts/setup/generate_secrets.py`, `docs/SECRETS.md`, iki yeni runbook.
- Filament 600 TRY/kg.

- **`PhysicsRunner`** (`platform/physics.py`): adayı `neml-mcp-sim` ile koşar, sim'in
  çalıştırdığı politika hash'ini kanıt olarak ister. `spawn_robot(policy_path=)` ve
  `RunMetrics.policy_sha256` eklendi.
- **Eksik uçlar:** `GET /api/v1/audit` (lab `audit_log` köprüden yansıtılır),
  `GET /campaigns/{id}/candidates`, `GET /auth/devices`, `POST /print-jobs/{id}/qc`.
  Lab `print.cancel` ve `print.qc` komutlarını uygular (`bridge/fab_ops.py`); önceden
  reddediliyordu.
- **Blazor:** Beyin konsolu, Evrim, Genome ağacı, Skill, Üretim (kalite kontrol formu),
  Loglar, Ayarlar ekranları; görev oluşturma ve öncelik değiştirme.
- **Metrikler:** `neml_llm_requests_total` / `neml_llm_latency_seconds` bağlandı;
  `neml_sim_runs_total` ajan çalıştırmalarını da sayar.
- Mobil: denetim günlüğü artık sunucunun sırasıyla (yeniden eskiye) gösterilir.

#### Bilinen boşluklar

- **T-093 KiCad.** `hardware/electronics/templates/` içinde üç kart üreticisi
  vardır (güç dağıtım, sensör breakout, konnektör). Otomatik 3B çakışma testi
  ve BOM stok/fiyat kontrolü hâlâ yoktur (`docs/SPEC_BULGULARI.md`).
- Faz 2'nin Gazebo'ya bağlı kabul kriterleri (T-034, T-036) ve `pytest -m
  regression` paketi laboratuvar makinesinde koşar; GitHub runner'ında
  Gazebo yoktur, bu iş etiket kapılı `sim-regression-gazebo` işindedir.

#### Güvenlik

- §5 güvenlik katmanı `SAFETY.md` olarak yazıya geçirildi: L0 donanım
  tablosu, dağıtım kapıları 0-4, oturum öncesi zorunlu e-stop/watchdog
  testi ve kapı başarısız olduğunda izlenecek prosedür.
- `config/policy/tools.yaml` içindeki `global_forbidden` (`firmware.flash`,
  `safety.*`, `db.write_raw`) hiçbir agent tarafından aşılamaz.
- `neml_mcp_fab.start()` onay belirteci olmadan baskı başlatmaz (§5.2
  seviye 4); belirteç yazıcıya gönderilen isteğe konmaz.
- `.env` ve `data/` git dışında tutuluyor; `gitleaks` yerel kapıya eklendi.
  Sahibin gerçek e-posta adresi ağaçta tutulmaz: §1.2 yer tutucusu
  (`mustafa.gulsoy@neml.local`) kullanılır ve CI bunu ayrıca denetler.
