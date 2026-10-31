<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# NEML — Networked Evolutionary Machine Laboratory

[![Lisans: AGPL-3.0-or-later](https://img.shields.io/badge/lisans-AGPL--3.0--or--later-blue)](LICENSE)

**Açık kaynak.** Ticari amaçla kullanabilirsiniz; kullanırken NEML'e atıf yapmak
ve değiştirdiğiniz sürümü kaynağıyla birlikte yayımlamak zorundasınız
([Lisans ve atıf](#lisans-ve-atıf)).

NEML, kendi robot revizyonlarını **insan tasarım müdahalesi olmadan** üreten,
simülasyonda eleyen ve iyileşmeyi fiziksel ölçümle kanıtlayan kapalı devre bir
laboratuvardır. Kanıt yoksa üretilen şey tasarım değil, gürültüdür (§21).

Üç ayak: **lab istasyonu** (beyin, 3 GB VRAM'de vLLM, Gazebo Harmonic,
ROS 2 Jazzy, PostgreSQL 16 + pgvector), **uzak sunucu** (.NET 9 + SignalR +
Blazor WASM; laba asla bağlanmaz, yalnızca komut kuyruğu tutar) ve
**mobil** (Flutter; canlı durum, görev yönetimi, onay kapıları).

Ayırt edici karar: 1.5B model serbest kod yazmaz. LLM yalnızca sınıflandırır
(`guided_choice`) ve parametre doldurur (`guided_json`); geometri, şematik ve
davranış deterministik Python şablon motorlarından çıkar (§4.3).

## Neler yapar

- **Şablonsuz tasarım:** LLM mekanizma, kart ve robot parçalarını bir JSON *tarifi* olarak yazar; sunucu tarifi veri olarak doğrular, FreeCAD'de çizer (eskiz/çıkart/döndür/loft/boru, delik, kabuk, yuvarlama).
- **Mühendislik çıktısı:** üçüncü açı izdüşümlü teknik resim (SVG + DXF; ölçü, tolerans, delik konumu, kesit, pürüzlülük, konum toleransı çerçevesi), ISO 286 geçmeleri, standart parçalar, eşleştirmeli montaj, üretilebilirlik (DFM) önerileri ve sonlu eleman (FEM) çözümü. Ayrıntı: [docs/CAD.md](docs/CAD.md).
- **Kapalı döngü öğrenme:** otopilot dersleri kural olarak kabul eder, başarılı tarifler günlük `lora/sft.jsonl` eğitim dosyasına yazılır.
- **Fiziksel güvenlik:** E-stop ve watchdog kanıtı olmadan fiziksel görev kodla reddedilir ([SAFETY.md](SAFETY.md)).

## Depo yapısı

| Klasör | İçerik |
|---|---|
| `brain/` | Python beyin: LLM, evrim döngüsü, öğrenme, köprü (`neml_brain/`) |
| `mcp_servers/` | Araç sunucuları (FreeCAD/CAD, KiCad, slicer, git, pg ...); CAD: `neml_mcp_cad/` |
| `dotnet/` | .NET 9 API (`Neml.Api`), Blazor web (`Neml.Web`), CLI, testler |
| `mobile/` | Flutter mobil uygulama |
| `ros2_ws/` | ROS 2 paketleri (kontrol, güvenlik, algı, tanım) |
| `firmware/` | STM32 hareket, ESP32 yardımcı, güvenlik watchdog |
| `hardware/`, `manufacturing/` | Katalog, elektronik, genom; dilimleyici profilleri |
| `config/` | LLM, bütçe, MCP, platform ve politika ayarları |
| `deploy/`, `docker/` | Sunucu kurulumu (nginx, systemd, rancher), imajlar ve compose dosyaları |
| `design-system/` | Web arayüz tasarım sistemi |
| `docs/` | CAD, geçit, LoRA, kurulum belgeleri; `adr/` kararlar, `runbooks/` prosedürler |
| `NEML_SPEC.md` | Tek doğruluk kaynağı (kontrat) |

## Hızlı başlangıç

```
git clone https://github.com/Netim-ltd/NEML.git && cd NEML
cd brain && uv sync && uv run pytest        # beyin testleri
cd ../mcp_servers && python -m pytest tests # CAD ve araç sunucusu testleri
cd ../dotnet && dotnet test Neml.sln        # API ve web testleri
```

Tam kurulum sırası ve portlar aşağıda; CAD sunucusu için FreeCAD 1.0 ve gmsh gerekir (`docker/cad/Dockerfile`).

## ⚠️ Fiziksel çalışma öncesi

**[SAFETY.md](SAFETY.md) okunmadan hiçbir fiziksel oturum başlatılmaz.**
E-stop ve watchdog testi kayıtlı değilse `neml-brain` fiziksel görevi
kodla reddeder (§5.1).

## Kontrat

Tek doğruluk kaynağı **[NEML_SPEC.md](NEML_SPEC.md)**'dir. Bu README onun kısa
özetidir; çelişki halinde spec kazanır ve kendi kararını verme, bildir (§0, §2).
Gerekçeler [`docs/adr/`](docs/adr/), olay prosedürleri
[`docs/runbooks/`](docs/runbooks/) altındadır.

## Topoloji (§3)

```
┌─────────────────────────────────────────────────────────────────┐
│ UZAK SUNUCU (VPS / bulut)                                       │
│                                                                 │
│   neml-api (.NET 9)            PostgreSQL 16 (neml_cloud)       │
│   ├─ REST  /api/v1/*           ├─ ayna veri                     │
│   ├─ SignalR /hubs/live        ├─ komut kuyruğu                 │
│   └─ Blazor WASM (web UI)      └─ kullanıcı / cihaz / oturum    │
└───────────▲──────────────────────────────▲──────────────────────┘
            │ HTTPS + JWT                  │ Outbound WSS (kalıcı)
            │                              │ lab → sunucu
┌───────────┴───────────┐      ┌───────────┴──────────────────────┐
│ MOBİL (Flutter)       │      │ LAB İSTASYONU (Ubuntu 24.04)     │
│ Android / iOS         │      │                                  │
│ • canlı durum         │      │  neml-brain (FastAPI:8080)       │
│ • görev yönetimi      │      │  ├─ LangGraph orkestratör        │
│ • komut gönderme      │      │  ├─ MCP istemcileri              │
│ • onay kapıları       │      │  ├─ evrim döngüsü                │
│ • push bildirim       │      │  └─ cloud-bridge (WSS client)    │
└───────────────────────┘      │                                  │
                               │  vLLM (Docker :8000) — 3 GB GPU  │
                               │  PostgreSQL 16 (neml_local)      │
                               │  MCP sunucuları (:9101-9110)     │
                               │  Gazebo Harmonic (headless)      │
                               │  ROS 2 Jazzy (DOMAIN_ID=42)      │
                               └───────────┬──────────────────────┘
                                           │ WiFi 5 GHz / Zenoh
                     ┌─────────────────────┼─────────────────────┐
                     ▼                     ▼                     ▼
               ┌──────────┐          ┌──────────┐          ┌──────────┐
               │  R01     │          │  R02     │          │  R0N     │
               │ Pi5+STM32│          │          │          │          │
               │ +ESP32   │          │          │          │          │
               │ +Watchdog│          │          │          │          │
               └──────────┘          └──────────┘          └──────────┘
```
```

Lab dışarıdan erişilemez, bu yüzden bağlantıyı **her zaman lab başlatır**:
`cloud-bridge` uzak API'ye giden yönde kalıcı WSS açar ve komutları kuyruktan
çeker. Kopmada 1s→2s→4s… max 60s geri çekilme; lab çevrimdışıyken de tam
çalışır, telemetri yerel kuyruğa yazılır (§3.1).

## Portlar (§17.1)

| Port | Servis | Erişim |
|---|---|---|
| 8000 | vLLM | localhost |
| 8080 | neml-brain (FastAPI) | LAN |
| 8081 | neml-embed | localhost |
| 5432 | PostgreSQL (lab) | localhost |
| 9101-9110 | MCP sunucuları | localhost |
| 11345 | Gazebo transport | localhost |
| 7447 | Zenoh router | LAN |
| 443 | .NET API (uzak) | İnternet |

## Kurulum sırası (§17.4)

Sıra atlanamaz. Hedef: Ubuntu 24.04 LTS.

```bash
# 1. Sistem
sudo scripts/setup/01_system.sh          # Ubuntu paketleri, NVIDIA sürücü
sudo scripts/setup/02_ros2_jazzy.sh
sudo scripts/setup/03_gazebo_harmonic.sh
sudo scripts/setup/04_freecad_kicad_prusa.sh

# 2. Veritabanı
docker compose up -d postgres
alembic -c brain/alembic.ini upgrade head
psql -f scripts/db/seed.sql

# 3. AI
docker compose up -d vllm embed
curl localhost:8000/v1/models        # doğrulama

# 4. MCP
scripts/setup/05_mcp_servers.sh      # §6.1 doğrulama + kurulum
docker compose up -d mcp-sim mcp-fab mcp-genome

# 5. Beyin
docker compose up -d brain
curl localhost:8080/health

# 6. ROS 2
cd ros2_ws && colcon build --symlink-install && source install/setup.bash

# 7. Uzak sunucu (ayrı makine)
cd dotnet && dotnet publish -c Release && systemctl start neml-api

# 8. Mobil
cd mobile && flutter pub get && flutter build apk --release
```

Başlamadan önce `.env.example` → `.env` kopyalayın, `CHANGEME` değerlerini
doldurun. `.env` git'e **girmez** (§5.4).

## Konfigürasyon

`config/` altında: `llm.yaml` (§4.2/§4.4/§4.7), `mcp.yaml` (§6.5),
`budget.yaml` (§14.4), `gz_bridge.yaml` (§11.1/§17.2),
`policy/tools.yaml` (§5.4), `profiles/sim_{fast,lidar,visual}.yaml` (§4.5).
Her dosya hangi spec bölümünü uyguladığını başında yazar.

## Geliştirme kuralları

- Kod/commit **İngilizce**, dokümantasyon **Türkçe** (§0.8).
- Her modül testleriyle gelir; testsiz kod merge edilmez (§0.9).
- Her kaynak dosya §1.2 telif/SPDX başlığıyla başlar; `pre-commit` zorlar.
- Başka projenin GPL/AGPL/LGPL kodu bu ağaca kopyalanmaz; ayrı süreç olarak çağrılır (§1.3, ADR-008).
- Yerel kapı: `pre-commit run --all-files` (telif başlığı, kopyaleft taraması,
  ruff, ruff-format, mypy --strict brain/, bandit, gitleaks).

## Lisans ve atıf

NEML, **GNU AGPL-3.0-or-later** ile yayımlanır ([LICENSE](LICENSE)); atıf ve kaynak
şartları [NOTICE](NOTICE) dosyasındadır.

- **Serbest:** kullanmak, değiştirmek, ticari faaliyette bulunmak.
- **Atıf zorunlu:** ürününüz, hizmetiniz ya da yayınınız NEML'i kullanıyorsa
  "NEML (Mustafa Gulsoy) tabanlıdır" yazıp bu depoya bağlantı verin; `NOTICE` ve telif başlıklarını koruyun.
- **Yayımlama zorunlu:** NEML'i ya da değiştirilmiş sürümünü başkalarına çalıştırıyorsanız (ağ hizmeti dahil),
  o sürümün tam kaynağını (değişiklikleriniz, eklediğiniz tarif/kural/kod) aynı lisansla yayımlamalısınız.
- **Marka:** "NEML" adı ve logosu değiştirilmiş sürüme ad olarak verilemez.

Akademik kullanım için [CITATION.cff](CITATION.cff). Katkı: [CONTRIBUTING.md](CONTRIBUTING.md).
Güvenlik açığı bildirimi için herkese açık issue açmayın; [SECURITY.md](SECURITY.md).
