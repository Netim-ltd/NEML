# NEML — Uygulama Spesifikasyonu (Agent Brief)

**Networked Evolutionary Machine Laboratory**

**Sahip:** Mustafa Gülsoy
**Doküman sürümü:** 1.0
**Tarih:** 2026-09-15
**Durum:** Uygulamaya hazır — bu doküman implementasyon kontratıdır.

---

## 0. AGENT TALİMATI — ÖNCE BUNU OKU

Bu dosyayı uygulayacak agent için bağlayıcı kurallar:

1. **Bu doküman tek doğruluk kaynağıdır.** Burada yazan bir karar
   tartışmaya açık değildir. Çelişki görürsen dur ve bildir; kendi kararını
   verme.
2. **Hiçbir alan "TBD" değildir.** Eksik gördüğün bir şey varsa bu bir
   hatadır, raporla.
3. **Faz sırası atlanamaz.** §16'daki görev listesi (T-001…T-092) sıralıdır.
   Bir görevin kabul kriteri karşılanmadan sonraki göreve geçilmez.
4. **§5 (Güvenlik) hiçbir koşulda gevşetilemez.** Performans, kolaylık veya
   zaman baskısı gerekçe değildir.
5. **LLM serbest kod üretmez.** §4.3'teki kısıtlı üretim mimarisi zorunludur.
   "Model kod yazsın" yönünde bir sadeleştirme yapılamaz.
6. **Her artefakt sürümlenir ve kaynağı kaydedilir** (model, prompt hash,
   seed, girdi hash). Kaydı olmayan artefakt geçersizdir.
7. **Donanıma giden her eylem insan onayı gerektirir.** Onay kapıları koda
   gömülüdür; prompt ile atlanamaz.
8. Kod yorumları ve commit mesajları **İngilizce**, dokümantasyon **Türkçe**.
9. Her modül için testler aynı PR'da yazılır. Testsiz kod merge edilmez.

---

## 1. PROJE KİMLİĞİ VE HAKLAR

### 1.1 Sahiplik

Bu proje kapsamında üretilen **tüm** çıktıların her türlü fikri ve sınai
mülkiyet hakkı **Mustafa Gülsoy**'a aittir. Kapsam:

- Kaynak kodu (Python, C#, C/C++, Dart, SQL, shell)
- Mekanik tasarımlar (FreeCAD kaynak dosyaları, STEP, STL, 3MF, teknik resim)
- Elektronik tasarımlar (KiCad projeleri, şematik, PCB, gerber, BOM)
- URDF/SDF modelleri, simülasyon dünyaları, kalibrasyon verileri
- Robot genome tanımları, skill kütüphanesi, davranış ağaçları
- Eğitim verileri, telemetri, deney kayıtları, fitness sonuçları
- Bu sistem tarafından **otonom olarak üretilen** her tasarım, kod ve veri
- Dokümantasyon, mimari, arayüz tasarımları, marka ve isim ("NEML")

### 1.2 Lisans (açık kaynak)

NEML, **GNU AGPL-3.0-or-later** ile açık kaynaktır (`LICENSE`), ek olarak AGPL §7 uyarınca
atıf ve kaynak yayımlama şartları `NOTICE` dosyasındadır. Kısaca:

- Kullanabilir, değiştirebilir, **ticari faaliyette** bulunabilirsiniz.
- Kullanırken ya da dağıtırken **NEML'e ve yazarına atıf** (adı, depo bağlantısı, `NOTICE`) zorunludur.
- Değiştirdiğiniz sürümü (ağ üzerinden hizmet olarak sunmak dahil) **kaynağıyla birlikte aynı lisansla yayımlamak** zorundasınız.
- "NEML" adı ve logosu marka olarak yazara aittir; değiştirilmiş sürüm kendini NEML diye sunamaz.

Her kaynak dosyanın başına şu başlık eklenir (pre-commit hook ile denetlenir):

```
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
```

### 1.3 Üçüncü taraf lisansları — uyum notu

> Bu bölüm hukuki tavsiye değildir. Ticarileştirme öncesi bir fikri
> mülkiyet avukatına danışılmalıdır.

| Araç | Lisans | Sizin çıktınıza etkisi |
|---|---|---|
| FreeCAD | LGPL-2.1+ | **Yok.** Araç olarak kullanım çıktıyı etkilemez. FreeCAD kodunu değiştirip dağıtırsanız LGPL yükümlülüğü doğar. |
| KiCad | GPL-3.0 | **Yok.** Araçla üretilen tasarım sizindir. KiCad'i değiştirip dağıtmayın. |
| PrusaSlicer | AGPL-3.0 | **Dikkat.** Araç olarak CLI çağrısı sorun değil. Ancak PrusaSlicer kodunu bir ağ servisine gömerseniz AGPL kaynak açma yükümlülüğü doğar → **gömmeyin, alt süreç olarak çağırın.** |
| ROS 2 / Gazebo | Apache-2.0 | Yok. En serbest seçenek. |
| vLLM | Apache-2.0 | Yok. |
| PostgreSQL / pgvector | PostgreSQL Lic. / PostgreSQL Lic. | Yok. |
| Flutter / Dart | BSD-3 | Yok. |
| .NET / ASP.NET Core | MIT | Yok. |
| Qwen2.5 modelleri | Apache-2.0 (0.5B–14B) | Yok. **Model lisansını indirmeden önce doğrulayın**, aile içinde değişir. |
| FastAPI, LangGraph | MIT | Yok. |

**Kural:** başka bir projenin GPL/AGPL/LGPL kodu NEML kaynak ağacına kopyalanmaz.
Bu araçlar yalnızca **ayrı süreç** olarak (CLI veya MCP sunucusu) çağrılır; böylece
kendi lisanslarının yükümlülükleri NEML kodunu etkilemez.

---

## 2. KESİNLEŞMİŞ KARARLAR

Aşağıdaki tablo tartışmaya kapalıdır. Alternatif değerlendirmesi yapılmaz.

| Alan | Karar | Gerekçe |
|---|---|---|
| OS | Ubuntu 24.04 LTS | Jazzy + Harmonic tek hat |
| ROS 2 | Jazzy Jalisco | LTS, Harmonic ile resmi eşleşme |
| Simülasyon | Gazebo Harmonic + `ros_gz` | Tek ortam |
| **Isaac Sim / Isaac ROS** | **KULLANILMAYACAK** | Gereksiz karmaşıklık, GPU bütçesi yok |
| Veritabanı | PostgreSQL 16 + pgvector | Tek veri deposu |
| **Qdrant** | **KULLANILMAYACAK** | pgvector yeterli |
| LLM runtime | vLLM (Docker) | OpenAI-uyumlu API, guided decoding |
| **Ollama** | **KULLANILMAYACAK** | Tek runtime |
| GPU bütçesi | **3 GB VRAM** | Donanım kısıtı — tüm tasarımı belirler |
| CAD | FreeCAD 1.0 (headless) + Python API | Parametrik, STEP çıktısı |
| Blender | Yalnızca tanıtım medyası | FreeCAD kaynak geometrisinden fotoğraf, video ve montaj animasyonu üretir; parametrik tasarım veya imalat doğrulaması yapmaz. 2026-09-30 kullanıcı kararı. |
| EDA | KiCad 8 (CLI + Python) | |
| Dilimleme | PrusaSlicer CLI | Konsol modunda |
| G-code doğrulama | **Prusa G-code Viewer** | Görsel + otomatik kontrol |
| Yazıcı host | PrusaLink REST API | Prusa ekosistemi bütünlüğü |
| Beyin API | Python 3.12 + FastAPI | |
| Orkestrasyon | LangGraph (deterministik state machine) | |
| Uzak API | .NET 9 ASP.NET Core Web API + SignalR | |
| Web arayüz | Blazor WebAssembly (aynı .NET host) | Tek dil, tek deploy |
| Mobil | Flutter 3.x (Android + iOS) | |
| Konsol araçları | Python `nemlctl` + .NET `neml-cli` | |
| Middleware RMW | `rmw_zenoh_cpp` | WiFi swarm için |
| MCU (hareket) | STM32F446 + micro-ROS | 1 kHz kontrol |
| MCU (yardımcı) | ESP32-S3 + micro-ROS | Telemetri, düşük hızlı G/Ç |
| MCU (güvenlik) | ATmega328P | Bağımsız watchdog |
| Edge bilgisayar | Raspberry Pi 5 (8 GB) | |
| Lisans | Tescilli — Mustafa Gülsoy | §1 |

---

## 3. DAĞITIM TOPOLOJİSİ

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

### 3.1 NAT problemi ve çözümü

Lab istasyonu ev/ofis ağındadır, dışarıdan erişilemez. Bu nedenle:

- **Uzak sunucu asla laba bağlanmaz.**
- Lab istasyonundaki `cloud-bridge`, uzak API'ye **giden yönde** kalıcı bir
  WebSocket (WSS) açar ve açık tutar.
- Mobil/web'den gelen komutlar uzak sunucudaki **komut kuyruğuna** yazılır;
  bridge bunları çeker, uygular, sonucu geri yollar.
- Bağlantı koptuğunda: bridge 1s → 2s → 4s … max 60s üstel geri çekilme ile
  yeniden bağlanır. Lab **çevrimdışıyken de tam çalışır**; telemetri yerel
  kuyruğa yazılır ve bağlantı dönünce sıralı olarak gönderilir.
- Her mesajın `seq` (monoton artan) ve `idempotency_key` alanı vardır.
  Tekrarlanan mesajlar sunucuda sessizce yok sayılır.

---

## 4. YAPAY ZEKÂ KATMANI — 3 GB GERÇEĞİ

### 4.1 Donanım kısıtının anlamı

3 GB VRAM ile çalışabilecek model sınıfı **1.5B parametre, 4-bit kuantize**.
Bu boyuttaki bir model şunları **yapamaz**:

- Sıfırdan doğru FreeCAD Python scripti yazmak
- Şematik topolojisi tasarlamak
- Uzun bağlamlı mimari kararlar almak
- Güvenilir serbest-biçimli araç seçimi (tool calling) yapmak

Bu bir eksiklik değil, **tasarım girdisidir**. Mimari buna göre kurulmuştur.

### 4.2 vLLM konfigürasyonu (kesin)

```yaml
# docker/vllm/docker-compose.yml
services:
  vllm:
    image: vllm/vllm-openai:latest
    container_name: neml-vllm
    runtime: nvidia
    ports: ["8000:8000"]
    volumes: ["${HOME}/.cache/huggingface:/root/.cache/huggingface"]
    environment:
      - HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}
    command: >
      --model Qwen/Qwen2.5-Coder-1.5B-Instruct-AWQ
      --quantization awq
      --dtype half
      --max-model-len 4096
      --gpu-memory-utilization 0.88
      --enforce-eager
      --max-num-seqs 2
      --swap-space 2
      --disable-log-requests
      --guided-decoding-backend xgrammar
    deploy:
      resources:
        reservations:
          devices: [{driver: nvidia, count: 1, capabilities: [gpu]}]
```

**Parametre gerekçeleri:**

| Parametre | Değer | Neden |
|---|---|---|
| `--enforce-eager` | açık | CUDA graph belleği ~300-500 MB tasarruf |
| `--max-model-len` | 4096 | KV cache 3 GB'a sığsın |
| `--max-num-seqs` | 2 | Eşzamanlı istek belleği sınırlı |
| `--gpu-memory-utilization` | 0.88 | Sürücü/görüntü için pay bırak |
| `--guided-decoding-backend` | xgrammar | §4.3 için zorunlu |

**Model seçimi:** `Qwen2.5-Coder-1.5B-Instruct-AWQ` tek yerleşik modeldir.
İkinci model **yüklenmez** (bellek yok). Farklı görevler prompt profili ile
ayrılır (§4.4).

**Yedek model (daha da kısıtlı donanımda):** `Qwen2.5-0.5B-Instruct` —
yalnızca sınıflandırma ve yönlendirme yapabilir, parametre üretemez.
Bu durumda §4.3'teki `param_fill` adımı elle doldurulur.

### 4.3 Kısıtlı Üretim Mimarisi (ZORUNLU)

LLM hiçbir zaman serbest metin/kod üretmez. Üç aşamalı boru hattı:

```
┌──────────────┐   ┌───────────────────┐   ┌────────────────────┐
│ 1. SINIFLA   │→  │ 2. PARAMETRE DOLDUR│→ │ 3. ÜRET (DETERMİNİSTİK)│
│    (LLM)     │   │     (LLM)          │   │   (şablon motoru)     │
└──────────────┘   └───────────────────┘   └────────────────────┘
  enum çıktı        JSON Schema kısıtlı      Python — LLM yok
  ~20 token         ~150 token               tam deterministik
```

**Aşama 1 — Sınıflandırma.** LLM, isteği sabit bir enum'a eşler.
Çıktı `guided_choice` ile kısıtlanır — model başka bir şey üretemez.

```python
INTENT = [
    "create_task", "update_task", "cancel_task",
    "query_status", "query_telemetry", "query_skill",
    "mech_param_change", "elec_param_change", "skill_tune",
    "run_sim_campaign", "explain", "unknown",
]
```

**Aşama 2 — Parametre doldurma.** LLM, ilgili niyetin JSON Schema'sına
uyan bir nesne üretir. `guided_json` ile şema zorlanır: şema dışı çıktı
üretilmesi **fiziksel olarak imkânsızdır** (grammar-constrained decoding).

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["template_id", "params"],
  "properties": {
    "template_id": {"enum": ["leg_link_v1","bracket_v1","foot_pad_v1",
                             "sensor_mount_v1","battery_tray_v1"]},
    "params": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "length_mm":    {"type": "number", "minimum": 60,  "maximum": 180},
        "width_mm":     {"type": "number", "minimum": 12,  "maximum": 45},
        "wall_mm":      {"type": "number", "minimum": 1.2, "maximum": 4.0},
        "infill_pct":   {"type": "integer","minimum": 15,  "maximum": 60},
        "rib_count":    {"type": "integer","minimum": 0,   "maximum": 6},
        "material":     {"enum": ["PETG","PA6-CF","PLA","ASA"]}
      }
    },
    "rationale": {"type": "string", "maxLength": 300}
  }
}
```

**Aşama 3 — Deterministik üretim.** JSON, elle yazılmış parametrik
FreeCAD/KiCad şablonuna verilir. Bu adımda LLM yoktur, çıktı %100
tekrarlanabilirdir.

```python
# brain/neml_brain/generators/mech.py
def generate(template_id: str, params: dict) -> MechArtifact:
    tpl = TEMPLATES[template_id]          # elle yazılmış, test edilmiş
    validate_against_schema(params, tpl.schema)
    validate_dfm(params)                  # §12.3 baskı kısıtları
    return tpl.build(params)              # FreeCAD headless çağrısı
```

**Sonuç:** Model küçüklüğü doğruluk riskini artırmaz. Model yanlış parametre
seçse bile geometri her zaman geçerli, üretilebilir ve şema-uyumludur.
Yanlış parametre simülasyonda elenir.

### 4.4 Prompt profilleri

Her profil ayrı sistem promptu + ayrı şema + ayrı `max_tokens`. Tek model,
altı profil:

| Profil | max_tokens | Kısıt | Görev |
|---|---|---|---|
| `router` | 8 | `guided_choice` | Niyet sınıflandırma |
| `param_mech` | 256 | `guided_json` | Mekanik parametre |
| `param_elec` | 256 | `guided_json` | Elektronik parametre |
| `param_skill` | 256 | `guided_json` | Davranış parametresi |
| `failure_tag` | 64 | `guided_choice` | Başarısızlık modu etiketleme |
| `summarize` | 384 | serbest (yalnızca insana gösterilir) | Rapor metni |

`summarize` dışındaki hiçbir profilin çıktısı doğrudan sisteme girmez.

### 4.5 GPU çakışması ve mutex

3 GB'ı vLLM ve Gazebo aynı anda kullanamaz. Çözüm:

```python
# brain/neml_brain/runtime/gpu_lock.py
class GpuLock:
    """Tek GPU tüketicisi garantisi. Docker socket ile vLLM durdurulur."""
    async def acquire(self, consumer: str, timeout_s: float = 300): ...
    async def release(self, consumer: str): ...
```

**Politika:**

| Sim profili | Kamera | GPU | vLLM |
|---|---|---|---|
| `fast` (varsayılan) | yok | CPU-only render | çalışır |
| `lidar` | yok | CPU | çalışır |
| `visual` | var | GPU gerekli | **durdurulur** |

- Varsayılan simülasyon profili `fast`'tir: IMU, enkoder, temas, LiDAR
  sensörleri CPU üzerinde çalışır. Evrim döngüsünün %95'i bu profildedir.
- `visual` profili yalnızca algı skill'lerinde kullanılır. Orkestratör
  `neml-vllm` konteynerini durdurur, simülasyonu koşar, sonra başlatır.
  Yeniden başlatma süresi ~40 s; bu maliyet planlamaya dahildir.
- Gazebo headless çalışır: `gz sim -s -r --headless-rendering`.

### 4.6 Gömme (embedding) — CPU

GPU'da yer yok. Gömme modeli CPU'da çalışır:

| Ayar | Değer |
|---|---|
| Model | `intfloat/multilingual-e5-small` (384 boyut) |
| Runtime | ONNX Runtime, CPU, int8 kuantize |
| Servis | `neml-embed` FastAPI :8081 |
| Hız | ~40 chunk/s (8 çekirdek) |
| Depolama | PostgreSQL `vector(384)` + HNSW indeks |

### 4.7 Opsiyonel uzak model (varsayılan: kapalı)

`LLMProvider` arayüzü soyutlanmıştır. İleride daha güçlü model gerekirse
kod değişmeden sağlayıcı değiştirilir:

```python
class LLMProvider(Protocol):
    async def classify(self, prompt: str, choices: list[str]) -> str: ...
    async def fill(self, prompt: str, schema: dict) -> dict: ...
    async def summarize(self, prompt: str, max_tokens: int) -> str: ...
```

Uygulamalar: `VllmProvider` (aktif), `RemoteOpenAIProvider` (kapalı).
`config/llm.yaml` → `provider: vllm`. Bu kapalı yol **test edilir ama
kullanılmaz**; kapalı olması bir eksiklik değil, bilinçli karardır.

---

## 5. GÜVENLİK KATMANI

### 5.1 L0 — Donanım güvenliği (yazılımdan bağımsız)

| Bileşen | Spesifikasyon |
|---|---|
| E-stop | NC (normally closed) mantar buton, motor gücünü röle ile keser. Robot üzerinde + tezgâhta. |
| Watchdog MCU | ATmega328P. Ana kontrolcüden 50 ms'de bir heartbeat bekler. 150 ms yoksa motor rölesini açar. |
| Akım limiti | Donanımsal shunt + komparatör, 20 A'da kesme. Yazılım değiştiremez. |
| Tork limiti | STM32 firmware'inde `#define MAX_TORQUE_NM 2.5f` — derleme zamanı sabiti. |
| Batarya | BMS zorunlu (aşırı deşarj, aşırı akım, hücre dengeleme). LiPo safe bag'de saklanır/şarj edilir. |
| Yazıcı | Thermal runaway koruması aktif, akıllı priz ile uzaktan güç kesme, duman dedektörü. |

**Test zorunluluğu:** Her fiziksel çalışma oturumundan önce e-stop ve
watchdog testi yapılır, `safety_checks` tablosuna kaydedilir. Kayıt yoksa
`neml-brain` fiziksel görev başlatmayı reddeder (kod ile zorlanır).

### 5.2 Dağıtım kapıları

```
Seviye 0: SIM         → otomatik, onay yok
Seviye 1: BENCH       → tekerlekler havada, güç 30%, insan hazır    [ONAY]
Seviye 2: TETHERED    → sınırlı alan, e-stop elde                   [ONAY]
Seviye 3: FREE        → serbest çalışma                             [ONAY]
Seviye 4: MANUFACTURE → baskı / PCB siparişi / firmware flash       [ONAY]
```

Onaylar mobil uygulamaya push bildirim olarak gider, `approvals` tablosuna
kim/ne zaman/ne ile kaydedilir. Onay **zaman aşımlıdır** (varsayılan 24 saat),
süresi dolan onay isteği otomatik reddedilir.

### 5.3 Kod yürütme izolasyonu

AI'ın ürettiği hiçbir şey host üzerinde doğrudan çalışmaz:

```yaml
sandbox:
  runtime: docker
  image: neml/sandbox:1.0
  network: none
  read_only_rootfs: true
  writable_mounts: ["/work"]
  cpu_limit: "2.0"
  memory_limit: "2g"
  pids_limit: 256
  timeout_s: 180
  user: "1000:1000"
  cap_drop: ["ALL"]
  security_opt: ["no-new-privileges:true"]
```

Statik kontroller (sandbox'tan önce): `ruff`, `mypy --strict`, `bandit`,
yasaklı çağrı listesi (`os.system`, `subprocess` (izinli liste dışı),
`eval`, `exec`, `socket`, `ctypes`, `__import__`).

### 5.4 Prompt injection ve yetki modeli

- **Güvenilmez girdi:** sensör metni, log satırı, dosya adı, mobil kullanıcı
  mesajı, web içeriği. Bunlar prompt'a `<untrusted_data>` bloğu içinde,
  açık uyarıyla girer ve **asla talimat olarak yorumlanmaz.**
- **Statik araç politikası:** `config/policy/tools.yaml`. Bir agent'ın araç
  listesi çalışma zamanında genişletilemez.

```yaml
# config/policy/tools.yaml
agents:
  planner:
    tools: [db.read, sim.read, skill.read]
  mechanical:
    tools: [db.read, cad.generate, cad.export, sim.run]
    forbidden: [printer.*, firmware.*, kicad.order]
  manufacturing:
    tools: [db.read, slicer.slice, gcode.validate, printer.status]
    requires_approval: [printer.start]
  electronics:
    tools: [db.read, kicad.generate, kicad.drc, kicad.bom]
    requires_approval: [kicad.gerber_export]
global_forbidden:
  - firmware.flash          # yalnızca insan, CLI ile
  - safety.*                # L0 hiçbir agent tarafından erişilemez
  - db.write_raw
```

- **Sırlar:** API anahtarı, SSH, DB parolası, fab hesabı LLM bağlamına
  **hiç girmez.** Sırlar `systemd` credentials veya `.env` ile yalnızca
  süreç ortamındadır.
- **Denetim günlüğü:** her araç çağrısı `audit_log` tablosuna yazılır:
  agent, araç, parametre hash, sonuç, süre, onay referansı.

### 5.5 Kimlik doğrulama (mobil/web)

| Katman | Yöntem |
|---|---|
| Mobil/web → .NET API | JWT (HS256, 15 dk) + refresh token (30 gün, rotasyonlu) |
| Lab bridge → .NET API | Uzun ömürlü API anahtarı + IP kısıtı; başlıkta `X-NEML-Node` |
| Roller | `owner` (tam yetki), `operator` (görev + onay), `viewer` (salt okuma) |
| Onay yetkisi | Yalnızca `owner` ve `operator` |
| Seviye 4 onayı | Yalnızca `owner` |
| Şifre | Argon2id, min 12 karakter |
| Oran sınırı | 100 istek/dk/kullanıcı, 10 komut/dk |

---

## 6. MCP SUNUCULARI

> ⚠️ **DOĞRULAMA ZORUNLU.** Bu oturumda internet erişimim yok. Aşağıdaki
> depo adresleri eğitim verimden gelmektedir ve **Mayıs 2026 öncesine**
> aittir. Kurulumdan önce her adresi tarayıcıda açıp doğrulayın. Adres
> ölmüşse veya depo terk edilmişse, "Kendi yazılacak" satırındaki
> spesifikasyona göre kendi sunucunuzu yazın — mimari buna hazırdır.

### 6.1 Hazır MCP sunucuları (doğrulanacak)

| # | Araç | Aday depo | Güven | Eylem |
|---|---|---|---|---|
| 1 | FreeCAD | `github.com/neka-nat/freecad-mcp` | Orta | Doğrula → kur |
| 2 | KiCad | `github.com/lamaalrajih/kicad-mcp` | Orta | Doğrula → kur |
| 3 | ROS 2 | `github.com/lpigeon/ros-mcp-server` | Orta | Doğrula → değerlendir |
| 4 | PostgreSQL | `github.com/crystaldba/postgres-mcp` | Orta-Yüksek | Doğrula → kur (salt okunur rol!) |
| 5 | Filesystem | `github.com/modelcontextprotocol/servers` → `src/filesystem` | Yüksek | Kur |
| 6 | Git | `github.com/modelcontextprotocol/servers` → `src/git` | Yüksek | Kur |
| 7 | Fetch | `github.com/modelcontextprotocol/servers` → `src/fetch` | Yüksek | Kur (yalnızca beyaz liste) |
| 8 | Docker | `github.com/ckreiling/mcp-server-docker` | Düşük-Orta | Doğrula → aksi halde kendi yaz |
| 9 | OpenSCAD | `github.com/jhacksman/OpenSCAD-MCP-Server` | Düşük | Doğrula → opsiyonel |

**Genel arama stratejisi** (adresler tutmazsa):
GitHub'da `topic:mcp <araç adı>`, `mcp-server-<araç>`, `<araç>-mcp` şeklinde
arayın. MCP resmi dizini: `github.com/modelcontextprotocol/servers` içindeki
"Community Servers" listesi.

### 6.2 Kendi yazılacak MCP sunucuları

Aşağıdakiler için olgun bir hazır çözüm beklemeyin. Spesifikasyonları
verilmiştir; her biri ~300-600 satır Python.

| # | Sunucu | Port | Neden kendi |
|---|---|---|---|
| 10 | `neml-mcp-sim` (Gazebo) | 9101 | Deterministik seed + GPU mutex gerektirir; genel çözüm yok |
| 11 | `neml-mcp-fab` (PrusaSlicer + G-code Viewer + PrusaLink) | 9102 | AGPL nedeniyle alt süreç zorunlu |
| 12 | `neml-mcp-genome` | 9103 | Projeye özgü |
| 13 | `neml-mcp-cad` (FreeCAD sarmalayıcı) | 9104 | #1 yetersizse yedek; şablon motoruna bağlı |

**Transport:** Tüm iç sunucular **Streamable HTTP** (stdio değil) kullanır —
daemon mimarisi ve GPU mutex bunu gerektirir.

### 6.3 `neml-mcp-sim` arayüz sözleşmesi

```python
set_seed(seed: int) -> None
load_world(world_id: str, seed: int, profile: Literal["fast","lidar","visual"]) -> WorldHandle
spawn_robot(urdf_path: str, pose: Pose, ns: str) -> RobotHandle
step(duration_s: float) -> SimTime                       # senkron, deterministik
run_until(condition: str, timeout_s: float) -> RunResult
read_sensor(robot: RobotHandle, sensor: str) -> SensorReading   # SI birimleri
capture_camera(robot: RobotHandle, cam: str) -> ImageRef        # yol döner, veri değil
get_contacts(robot: RobotHandle) -> list[Contact]               # Newton
apply_wrench(link: str, force_N: Vec3, torque_Nm: Vec3) -> None
get_metrics(robot: RobotHandle) -> RunMetrics
reset(handle: WorldHandle) -> None
teardown(handle: WorldHandle) -> None
```

Kurallar: tüm birimler SI; süresiz blocking çağrı yok; görüntü/pointcloud
referansla döner; aynı seed + aynı sürüm hash = aynı sonuç (±%2 metrik
toleransı); her çağrıda timeout ve tipli hata zorunlu.

### 6.4 `neml-mcp-fab` arayüz sözleşmesi

```python
slice(model_3mf: str, profile_id: str) -> GcodeResult
# prusa-slicer --export-gcode --load <profile.ini> --output <out.gcode> <in.3mf>

validate_gcode(gcode_path: str) -> GcodeReport
# prusa-gcodeviewer --export-png <out.png> <in.gcode>  → görsel
# + ayrıştırıcı: süre, filament (g/mm), katman sayısı, max sıcaklık,
#   retraction sayısı, köprü uzunlukları, destek hacmi

estimate(gcode_path: str) -> {time_h, filament_g, cost_try}
upload(gcode_path: str, printer_id: str) -> FileHandle
# PrusaLink: PUT /api/v1/files/usb/<name>  (X-Api-Key)
start(file: FileHandle, printer_id: str, approval_token: str) -> JobHandle
# PrusaLink: POST /api/v1/job  — approval_token ZORUNLU
status(printer_id: str) -> PrinterStatus
# PrusaLink: GET /api/v1/status
cancel(job: JobHandle) -> None
```

**Prusa G-code Viewer kullanımı** — iki modda:
1. **Otomatik doğrulama:** `prusa-gcodeviewer` CLI ile PNG önizleme üretilir,
   `validate_gcode` raporu ile birlikte onay ekranına düşer.
2. **İnsan incelemesi:** Onay kapısında mobil uygulamada bu PNG gösterilir;
   operatör baskıyı görsel olarak onaylar.

### 6.5 MCP istemci konfigürasyonu

```yaml
# config/mcp.yaml
servers:
  freecad:   {url: "http://127.0.0.1:9104/mcp", timeout_s: 120, retries: 2}
  kicad:     {url: "http://127.0.0.1:9105/mcp", timeout_s: 180, retries: 1}
  sim:       {url: "http://127.0.0.1:9101/mcp", timeout_s: 600, retries: 0}
  fab:       {url: "http://127.0.0.1:9102/mcp", timeout_s: 120, retries: 1}
  genome:    {url: "http://127.0.0.1:9103/mcp", timeout_s: 30,  retries: 2}
  postgres:  {url: "http://127.0.0.1:9106/mcp", timeout_s: 30,  retries: 2, role: readonly}
  filesystem:{url: "http://127.0.0.1:9107/mcp", timeout_s: 30,  retries: 2,
              allowed_paths: ["/srv/neml/work", "/srv/neml/artifacts"]}
  git:       {url: "http://127.0.0.1:9108/mcp", timeout_s: 60,  retries: 1}
```

**Kritik:** 1.5B model güvenilir araç seçimi yapamaz. Bu yüzden MCP
çağrıları **LangGraph düğümleri tarafından deterministik olarak** yapılır;
model yalnızca parametreleri doldurur. "Modele araç listesi ver, seçsin"
yaklaşımı bu projede **yasaktır**.

---

## 7. VERİTABANI ŞEMASI (PostgreSQL 16 + pgvector)

İki örnek: `neml_local` (lab, otoriter) ve `neml_cloud` (uzak, ayna +
komut kuyruğu). Şema ortaktır; `neml_cloud`'da `users`, `devices`,
`commands`, `approvals` ek tablolardır.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============ ROBOT & GENOME ============
CREATE TABLE genomes (
    id              TEXT PRIMARY KEY,              -- quadruped_v2@a3f91c7
    name            TEXT NOT NULL,
    version         INT  NOT NULL,
    hash            TEXT NOT NULL UNIQUE,
    parent_id       TEXT REFERENCES genomes(id),
    status          TEXT NOT NULL CHECK (status IN ('draft','testing','active','deprecated')),
    body            JSONB NOT NULL,                -- §13 şeması
    limits          JSONB NOT NULL,                -- değiştirilemez
    fitness_score   NUMERIC(6,4),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON genomes (status);
CREATE INDEX ON genomes (parent_id);

CREATE TABLE robots (
    id              TEXT PRIMARY KEY,              -- R01
    genome_id       TEXT NOT NULL REFERENCES genomes(id),
    namespace       TEXT NOT NULL UNIQUE,
    hostname        TEXT NOT NULL,
    state           TEXT NOT NULL CHECK (state IN
                      ('offline','idle','charging','running','fault','estop','maintenance')),
    battery_soc     NUMERIC(4,3),
    last_seen       TIMESTAMPTZ,
    calibrated_at   TIMESTAMPTZ,
    reality_gap     NUMERIC(5,4),                  -- §11.3
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ SKILL ============
CREATE TABLE skills (
    id              TEXT PRIMARY KEY,              -- climb_small_obstacle@3
    skill_key       TEXT NOT NULL,
    version         INT  NOT NULL,
    genome_id       TEXT NOT NULL REFERENCES genomes(id),
    bt_path         TEXT NOT NULL,                 -- behavior tree xml
    parameters      JSONB NOT NULL,
    preconditions   JSONB NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('candidate','validated','retired')),
    supersedes      TEXT REFERENCES skills(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (skill_key, version)
);

CREATE TABLE skill_validations (
    id              BIGSERIAL PRIMARY KEY,
    skill_id        TEXT NOT NULL REFERENCES skills(id),
    env             TEXT NOT NULL CHECK (env IN ('sim','real')),
    trials          INT  NOT NULL CHECK (trials > 0),
    successes       INT  NOT NULL,
    ci95_low        NUMERIC(5,4) NOT NULL,
    ci95_high       NUMERIC(5,4) NOT NULL,
    seeds           INT[] NOT NULL,
    failure_modes   JSONB NOT NULL DEFAULT '[]',
    run_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ TASK ============
CREATE TABLE tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN
                      ('human','repair','exploration','evolution','maintenance','calibration')),
    source          TEXT NOT NULL,                 -- user:mg | auto:failure | auto:coverage
    priority        NUMERIC(6,3) NOT NULL,         -- §14.2 formülü
    state           TEXT NOT NULL CHECK (state IN
                      ('queued','planning','awaiting_approval','running','paused',
                       'succeeded','failed','cancelled')),
    robot_id        TEXT REFERENCES robots(id),
    spec            JSONB NOT NULL,
    result          JSONB,
    deadline        TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON tasks (state, priority DESC);

CREATE TABLE task_runs (
    id              BIGSERIAL PRIMARY KEY,
    task_id         UUID NOT NULL REFERENCES tasks(id),
    attempt         INT  NOT NULL,
    env             TEXT NOT NULL CHECK (env IN ('sim','bench','tethered','free')),
    seed            BIGINT,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    outcome         TEXT CHECK (outcome IN ('success','failure','aborted','timeout')),
    metrics         JSONB,
    rosbag_path     TEXT,
    UNIQUE (task_id, attempt)
);

-- ============ EVOLUTION ============
CREATE TABLE campaigns (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    objective       TEXT NOT NULL,
    weights         JSONB NOT NULL,                -- ÖNCEDEN sabitlenir
    budget          JSONB NOT NULL,                -- §14.4
    state           TEXT NOT NULL CHECK (state IN ('active','stopped','completed')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ
);

CREATE TABLE candidates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID NOT NULL REFERENCES campaigns(id),
    generation      INT  NOT NULL,
    genome_id       TEXT NOT NULL REFERENCES genomes(id),
    operator        TEXT NOT NULL CHECK (operator IN
                      ('mutation','crossover','llm_guided','seed')),
    rationale       TEXT,
    llm_model       TEXT,
    prompt_hash     TEXT,
    fitness         NUMERIC(6,4),
    fitness_parts   JSONB,
    verdict         TEXT CHECK (verdict IN ('pending','sim_pass','sim_fail',
                                            'real_pass','real_fail','accepted','rejected')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sim_runs (
    id              BIGSERIAL PRIMARY KEY,
    candidate_id    UUID REFERENCES candidates(id),
    world_id        TEXT NOT NULL,
    seed            BIGINT NOT NULL,
    profile         TEXT NOT NULL CHECK (profile IN ('fast','lidar','visual')),
    sim_version     TEXT NOT NULL,
    duration_s      NUMERIC(8,2),
    metrics         JSONB NOT NULL,
    deterministic   BOOLEAN NOT NULL DEFAULT TRUE,
    run_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ MANUFACTURING ============
CREATE TABLE artifacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            TEXT NOT NULL CHECK (kind IN
                      ('cad_src','step','stl','3mf','gcode','kicad','gerber','bom','urdf','bt')),
    path            TEXT NOT NULL,
    sha256          TEXT NOT NULL,
    genome_id       TEXT REFERENCES genomes(id),
    generator       TEXT NOT NULL,                 -- template_id veya 'manual'
    input_hash      TEXT,
    llm_model       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE print_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id     UUID NOT NULL REFERENCES artifacts(id),
    printer_id      TEXT NOT NULL,
    profile_id      TEXT NOT NULL,
    approval_id     UUID NOT NULL,
    est_time_h      NUMERIC(6,2),
    est_filament_g  NUMERIC(8,2),
    est_cost_try    NUMERIC(10,2),
    state           TEXT NOT NULL CHECK (state IN
                      ('queued','printing','done','failed','cancelled')),
    qc              JSONB,                         -- §12.4 ölçümler
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ
);

CREATE TABLE bom_items (
    id              BIGSERIAL PRIMARY KEY,
    genome_id       TEXT NOT NULL REFERENCES genomes(id),
    ref             TEXT NOT NULL,
    part_number     TEXT NOT NULL,
    qty             INT NOT NULL,
    unit_cost_try   NUMERIC(10,2),
    supplier        TEXT,
    lead_time_days  INT
);

-- ============ TELEMETRY (aylık partisyon) ============
CREATE TABLE telemetry (
    ts              TIMESTAMPTZ NOT NULL,
    robot_id        TEXT NOT NULL,
    metric          TEXT NOT NULL,
    value           DOUBLE PRECISION NOT NULL,
    tags            JSONB
) PARTITION BY RANGE (ts);
-- scripts/db/create_partitions.sh her ay çalışır (systemd timer)
CREATE INDEX ON telemetry (robot_id, metric, ts DESC);

-- ============ GÜVENLİK & DENETİM ============
CREATE TABLE approvals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    level           INT NOT NULL CHECK (level BETWEEN 1 AND 4),
    subject_kind    TEXT NOT NULL,                 -- task | print | gerber | firmware
    subject_id      TEXT NOT NULL,
    payload         JSONB NOT NULL,                -- özet + önizleme yolu
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    decided_at      TIMESTAMPTZ,
    decided_by      TEXT,
    decision        TEXT CHECK (decision IN ('approved','rejected','expired')),
    note            TEXT
);

CREATE TABLE safety_checks (
    id              BIGSERIAL PRIMARY KEY,
    robot_id        TEXT NOT NULL REFERENCES robots(id),
    estop_ok        BOOLEAN NOT NULL,
    watchdog_ok     BOOLEAN NOT NULL,
    current_limit_ok BOOLEAN NOT NULL,
    performed_by    TEXT NOT NULL,
    performed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor           TEXT NOT NULL,                 -- agent:mechanical | user:mg
    action          TEXT NOT NULL,
    target          TEXT,
    params_hash     TEXT,
    outcome         TEXT,
    duration_ms     INT,
    approval_id     UUID REFERENCES approvals(id)
);
CREATE INDEX ON audit_log (ts DESC);

-- ============ BELLEK (pgvector) ============
CREATE TABLE memory_chunks (
    id              BIGSERIAL PRIMARY KEY,
    source_kind     TEXT NOT NULL,                 -- failure | doc | skill | note
    source_id       TEXT,
    content         TEXT NOT NULL,
    embedding       vector(384) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON memory_chunks USING hnsw (embedding vector_cosine_ops);

-- ============ SADECE neml_cloud ============
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,                 -- argon2id
    role            TEXT NOT NULL CHECK (role IN ('owner','operator','viewer')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE devices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    platform        TEXT NOT NULL CHECK (platform IN ('android','ios','web')),
    push_token      TEXT,
    last_seen       TIMESTAMPTZ
);

CREATE TABLE commands (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    seq             BIGSERIAL,
    kind            TEXT NOT NULL,                 -- §9.3 komut tipleri
    payload         JSONB NOT NULL,
    state           TEXT NOT NULL CHECK (state IN
                      ('pending','delivered','applied','failed','rejected')),
    result          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_at      TIMESTAMPTZ
);
CREATE INDEX ON commands (state, seq);
```

**Saklama politikası:**

| Veri | Süre | Sonra |
|---|---|---|
| `telemetry` ham | 90 gün | 1 dk'lık ortalamaya indir, 2 yıl sakla |
| `rosbag2` | 30 gün | Yalnızca başarısız koşular arşivlenir |
| `sim_runs` | Süresiz | Metrik küçük |
| `audit_log` | 2 yıl | Arşiv |
| `artifacts` | Süresiz | git-lfs |

---

## 8. `neml-brain` — Python FastAPI

### 8.1 Teknoloji

| Bileşen | Sürüm/Seçim |
|---|---|
| Python | 3.12 |
| Web | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.0 (async) + Alembic |
| Orkestrasyon | LangGraph (PostgreSQL checkpointer) |
| Görev kuyruğu | APScheduler (yerel, harici broker yok) |
| HTTP istemci | httpx |
| Validasyon | Pydantic v2 |
| Log | structlog (JSON) |
| Metrik | prometheus-client `:8080/metrics` |
| Test | pytest + pytest-asyncio + testcontainers |

### 8.2 Modül yapısı

```
brain/neml_brain/
├─ api/            # FastAPI router'ları
├─ agents/         # LangGraph düğümleri
│  ├─ orchestrator.py planner.py coding.py memory.py
│  ├─ perception.py swarm.py reflection.py
│  └─ mechanical.py electronics.py manufacturing.py evolution.py
├─ llm/            # LLMProvider, profiller, şemalar
├─ generators/     # DETERMİNİSTİK şablon motorları
│  ├─ mech.py      # FreeCAD şablonları
│  ├─ elec.py      # KiCad şablonları
│  └─ behavior.py  # BT şablonları
├─ mcp/            # MCP istemcileri
├─ memory/         # pgvector arama, chunk'lama
├─ evolution/      # fitness, operatörler, seçilim
├─ runtime/        # gpu_lock, sandbox, budget
├─ safety/         # kapılar, politika motoru
├─ bridge/         # cloud-bridge (WSS client)
├─ db/             # modeller, migration
└─ autonomy/       # sürekli döngü, görev keşfi (§14)
```

### 8.3 REST API (lab içi, :8080)

| Metot | Yol | Açıklama |
|---|---|---|
| GET | `/health` | Canlılık + bileşen durumu |
| GET | `/v1/robots` | Robot listesi + durum |
| GET | `/v1/robots/{id}` | Detay |
| POST | `/v1/robots/{id}/estop` | Yazılımsal durdurma (L0 ayrı) |
| GET | `/v1/tasks` | Filtreli görev listesi |
| POST | `/v1/tasks` | Görev oluştur |
| PATCH | `/v1/tasks/{id}` | Güncelle (öncelik, spec, durum) |
| DELETE | `/v1/tasks/{id}` | İptal |
| GET | `/v1/tasks/{id}/runs` | Koşu geçmişi |
| POST | `/v1/command` | Doğal dil komut → §4.3 boru hattı |
| GET | `/v1/skills` | Skill kütüphanesi |
| GET | `/v1/genomes` | Genome soy ağacı |
| POST | `/v1/campaigns` | Evrim kampanyası başlat |
| GET | `/v1/campaigns/{id}` | İlerleme + fitness grafiği verisi |
| POST | `/v1/campaigns/{id}/stop` | Durdur |
| GET | `/v1/approvals` | Bekleyen onaylar |
| POST | `/v1/approvals/{id}/decide` | Onay/ret |
| GET | `/v1/telemetry` | Zaman serisi sorgusu |
| POST | `/v1/sim/run` | Tek seferlik simülasyon |
| GET | `/v1/budget` | Günlük bütçe kullanımı |
| POST | `/v1/runtime/llm/{start\|stop}` | GPU mutex yönetimi |
| GET | `/metrics` | Prometheus |

Tüm yanıtlar `application/json`. Hata formatı RFC 7807 `application/problem+json`.

### 8.4 LangGraph akışı (ana döngü)

```
                  ┌──────────────┐
      komut ──────▶│  ROUTER      │ (LLM: guided_choice)
                  └──────┬───────┘
                         │
        ┌────────────────┼────────────────┬─────────────────┐
        ▼                ▼                ▼                 ▼
   ┌─────────┐     ┌──────────┐    ┌───────────┐     ┌──────────┐
   │ QUERY   │     │ TASK_OPS │    │ DESIGN    │     │ EXPLAIN  │
   │ (DB)    │     │ (CRUD)   │    │           │     │ (LLM sum)│
   └────┬────┘     └────┬─────┘    └─────┬─────┘     └────┬─────┘
        │               │                │                 │
        │               │          ┌─────▼──────┐          │
        │               │          │ PARAM_FILL │ (LLM: guided_json)
        │               │          └─────┬──────┘          │
        │               │          ┌─────▼──────┐          │
        │               │          │ GENERATE   │ (deterministik)
        │               │          └─────┬──────┘          │
        │               │          ┌─────▼──────┐          │
        │               │          │ VALIDATE   │ (DFM/DRC/şema)
        │               │          └─────┬──────┘          │
        │               │          ┌─────▼──────┐          │
        │               │          │ SIMULATE   │◀─┐       │
        │               │          └─────┬──────┘  │ fail  │
        │               │                ├─────────┘       │
        │               │          ┌─────▼──────┐          │
        │               │          │ APPROVAL   │ (insan)  │
        │               │          └─────┬──────┘          │
        │               │          ┌─────▼──────┐          │
        │               │          │ EXECUTE    │          │
        │               │          └─────┬──────┘          │
        └───────────────┴────────────────┴─────────────────┘
                                 │
                          ┌──────▼──────┐
                          │   PERSIST   │  (DB + audit + bridge)
                          └─────────────┘
```

**Checkpoint:** Her düğüm sonrası durum PostgreSQL'e yazılır. Süreç çökerse
kaldığı yerden devam eder. Maksimum düğüm adımı: 25 (sonsuz döngü koruması).

---

## 9. `neml-api` — .NET 9 Web API (Uzak Sunucu)

### 9.1 Proje yapısı

```
dotnet/
├─ Neml.Api/                 # ASP.NET Core Web API + SignalR + Blazor host
│  ├─ Program.cs
│  ├─ Controllers/
│  ├─ Hubs/LiveHub.cs
│  ├─ Services/
│  └─ appsettings.json
├─ Neml.Domain/              # Entity, enum, DTO
├─ Neml.Infrastructure/      # EF Core (Npgsql), repository
├─ Neml.Web/                 # Blazor WebAssembly (web arayüz)
├─ Neml.Cli/                 # Konsol yönetim aracı
└─ Neml.Tests/               # xUnit
```

### 9.2 Bağımlılıklar

| Paket | Amaç |
|---|---|
| `Npgsql.EntityFrameworkCore.PostgreSQL` | DB |
| `Microsoft.AspNetCore.SignalR` | Canlı yayın |
| `Microsoft.AspNetCore.Authentication.JwtBearer` | Auth |
| `Serilog.AspNetCore` | Log |
| `FluentValidation.AspNetCore` | Doğrulama |
| `Swashbuckle.AspNetCore` | OpenAPI |
| `FirebaseAdmin` | Push bildirim (FCM) |
| `Isopoh.Cryptography.Argon2` | Şifre |

### 9.3 REST endpoint'leri (`/api/v1`)

**Auth**
| Metot | Yol |
|---|---|
| POST | `/auth/login` → `{access, refresh}` |
| POST | `/auth/refresh` |
| POST | `/auth/logout` |
| POST | `/auth/devices` (push token kaydı) |

**Robotlar**
| Metot | Yol |
|---|---|
| GET | `/robots` |
| GET | `/robots/{id}` |
| GET | `/robots/{id}/telemetry?metric=&from=&to=&agg=` |
| POST | `/robots/{id}/estop` → komut kuyruğu |

**Görevler**
| Metot | Yol |
|---|---|
| GET | `/tasks?state=&kind=&robot=&page=` |
| GET | `/tasks/{id}` |
| POST | `/tasks` |
| PATCH | `/tasks/{id}` |
| POST | `/tasks/{id}/cancel` |
| GET | `/tasks/{id}/runs` |

**Beyin komutu (LLM)**
| Metot | Yol |
|---|---|
| POST | `/brain/command` → `{text}` → komut kuyruğuna yazar, `command_id` döner |
| GET | `/brain/command/{id}` → uygulanma durumu + sonuç |
| GET | `/brain/status` → beyin canlı mı, model, GPU durumu |

**Eğitim / evrim**
| Metot | Yol |
|---|---|
| GET | `/campaigns` |
| GET | `/campaigns/{id}` |
| POST | `/campaigns` |
| POST | `/campaigns/{id}/stop` |
| GET | `/campaigns/{id}/generations` → fitness serisi |
| GET | `/skills` |
| GET | `/skills/{key}/versions` |
| GET | `/genomes/tree` → soy ağacı (mobil görselleştirme) |

**Onaylar**
| Metot | Yol |
|---|---|
| GET | `/approvals?pending=true` |
| GET | `/approvals/{id}` (önizleme PNG dahil) |
| POST | `/approvals/{id}/approve` |
| POST | `/approvals/{id}/reject` |

**Üretim**
| Metot | Yol |
|---|---|
| GET | `/print-jobs` |
| GET | `/printers/{id}/status` |
| POST | `/print-jobs/{id}/cancel` |

**Bridge (yalnızca lab, API anahtarı ile)**
| Metot | Yol |
|---|---|
| WS | `/bridge/ws` — çift yönlü |
| POST | `/bridge/telemetry/batch` — çevrimdışı birikmiş veri |
| POST | `/bridge/events` |

### 9.4 SignalR — `/hubs/live`

**Sunucu → İstemci olayları**

| Olay | Yük |
|---|---|
| `RobotState` | `{robotId, state, batterySoc, lastSeen}` |
| `TelemetryTick` | `{robotId, metrics: {...}, ts}` (1 Hz, throttled) |
| `TaskUpdated` | `{taskId, state, progress, message}` |
| `TaskRunEvent` | `{taskId, attempt, env, outcome?, step}` |
| `CampaignProgress` | `{campaignId, generation, best, mean, candidatesDone}` |
| `ApprovalRequested` | `{approvalId, level, subject, expiresAt, previewUrl}` |
| `ApprovalDecided` | `{approvalId, decision, by}` |
| `PrintProgress` | `{jobId, pct, layer, etaMin, nozzleC, bedC}` |
| `BrainStatus` | `{online, model, gpuOwner, budgetUsed}` |
| `Alert` | `{severity, code, message}` |

**İstemci → Sunucu**

| Metot | Açıklama |
|---|---|
| `SubscribeRobot(robotId)` | Grup aboneliği |
| `SubscribeCampaign(campaignId)` | |
| `UnsubscribeAll()` | |

**Gruplar:** `robot:{id}`, `campaign:{id}`, `approvals`, `global`.

### 9.5 Bridge protokolü (WSS, lab ↔ sunucu)

Mesaj zarfı:

```json
{
  "v": 1,
  "seq": 128394,
  "ts": "2026-09-15T10:22:31.442Z",
  "type": "telemetry|event|command_ack|state|log",
  "idempotency_key": "b3f1...",
  "payload": { }
}
```

- **Lab → Sunucu:** `telemetry` (toplu, 1 Hz), `state`, `event`,
  `command_ack`, `approval_request`, `log`.
- **Sunucu → Lab:** `command` (kuyruktan), `approval_decision`, `ping`.
- **Heartbeat:** 15 s. 45 s yanıtsızlık → bağlantı kopuk sayılır,
  `BrainStatus{online:false}` yayınlanır.
- **Sıkıştırma:** permessage-deflate.
- **Kuyruk:** Lab tarafında SQLite tabanlı kalıcı kuyruk (`/var/lib/neml/outbox.db`),
  max 500 MB, FIFO, dolunca en eski telemetri düşürülür (event ve ack asla düşmez).

---

## 10. FLUTTER MOBİL UYGULAMA

### 10.1 Teknoloji

| Bileşen | Seçim |
|---|---|
| Flutter | 3.24+ / Dart 3.5+ |
| State | Riverpod 2 (`AsyncNotifier`) |
| Yönlendirme | go_router |
| HTTP | dio + `dio_smart_retry` |
| Realtime | `signalr_netcore` |
| Grafik | fl_chart |
| Güvenli depolama | flutter_secure_storage |
| Yerel önbellek | drift (SQLite) |
| Push | firebase_messaging + flutter_local_notifications |
| i18n | `flutter_localizations` — TR birincil, EN ikincil |
| Tema | Material 3, koyu tema varsayılan |

### 10.2 Ekranlar

| # | Ekran | İçerik |
|---|---|---|
| 1 | **Giriş** | E-posta/şifre, biyometrik kilit, sunucu adresi ayarı |
| 2 | **Panel (Dashboard)** | Beyin durumu (online/model/GPU), robot kartları (durum, batarya, mevcut görev), bekleyen onay rozeti, günlük bütçe çubukları, son 5 alarm |
| 3 | **Robot Detay** | Canlı telemetri (batarya, akım, sıcaklık, eklem yükü — fl_chart, 60 s pencere), durum makinesi, son koşular, e-stop butonu (çift onaylı kaydırma), kalibrasyon durumu + reality gap |
| 4 | **Görevler** | Sekmeler: Kuyruk / Çalışan / Tamamlanan. Kart: başlık, tip rozeti, öncelik, robot, ilerleme. Kaydırma: öncelik değiştir / iptal. FAB: yeni görev |
| 5 | **Görev Detay** | Spec JSON (okunur biçim), koşu geçmişi, metrikler, rosbag indirme, başarısızlık modları |
| 6 | **Beyin Konsolu** | Doğal dil komut girişi. Gönderilen komut → algılanan niyet → üretilen değişiklik → onay. Geçmiş sohbet benzeri liste. Hazır komut şablonları (çip butonlar) |
| 7 | **Eğitim / Evrim** | Aktif kampanya kartı: nesil, en iyi fitness, ortalama, kalan bütçe. Fitness eğrisi (nesil vs en iyi/ortalama). Aday listesi + verdict. Kampanya durdur |
| 8 | **Genome Ağacı** | Soy ağacı görselleştirme (basit dikey ağaç), düğüme dokun → genome özeti, aktif sürüm işareti |
| 9 | **Skill Kütüphanesi** | Skill listesi, sim/gerçek başarı oranı çubukları + güven aralığı, sürüm geçmişi, ön koşullar |
| 10 | **Onaylar** | Bekleyen liste, seviye rozeti (1-4), geri sayım. Detay: özet + G-code önizleme PNG + maliyet/süre. Onayla/Reddet + not. Seviye 4 için ek metin doğrulaması ("ONAYLIYORUM" yaz) |
| 11 | **Üretim** | Yazıcı durumu (sıcaklık, ilerleme, ETA), baskı kuyruğu, iptal, kalite kontrol formu (kumpas ölçümleri girişi) |
| 12 | **Loglar & Denetim** | Filtrelenebilir audit log, agent araç çağrıları, hata akışı |
| 13 | **Ayarlar** | Sunucu, bildirim tercihleri, tema, dil, oturumlar, çıkış |

### 10.3 Çevrimdışı davranış

- Son alınan durum drift ile önbelleğe alınır, açılışta anında gösterilir,
  üstte "çevrimdışı — son güncelleme HH:mm" bandı görünür.
- Çevrimdışıyken yazma işlemleri **kuyruğa alınmaz**, engellenir. Sebep:
  robotlara geç ulaşan komut tehlikelidir. Kullanıcıya net mesaj verilir.
- Tek istisna: onay **reddi** kuyruğa alınabilir (güvenli yönde hata).

### 10.4 Push bildirimleri

| Tetik | Öncelik | Ses |
|---|---|---|
| Onay istendi (seviye 3-4) | Yüksek | Var |
| Robot `fault` / `estop` | Yüksek | Var |
| Görev başarısız (3. deneme) | Normal | Yok |
| Kampanya tamamlandı | Normal | Yok |
| Baskı bitti | Düşük | Yok |
| Bütçe %90 | Normal | Yok |

---

## 11. SİMÜLASYON

### 11.1 Ortam

- Gazebo Harmonic, `gz sim -s -r --headless-rendering`
- ROS 2 köprüsü: `ros_gz_bridge`, konfigürasyon `config/gz_bridge.yaml`
- Dünyalar: `ros2_ws/src/neml_sim/worlds/` — `flat.sdf`, `obstacle_low.sdf`,
  `ramp_10deg.sdf`, `rough_terrain.sdf`, `maze.sdf`
- Fizik: DART, `max_step_size: 0.001`, `real_time_factor: 0` (mümkün olan en hızlı)

### 11.2 Determinizm kuralları

1. Her koşu `seed` ile başlar; tüm rastgelelik bu seed'den türetilir.
2. `sim_version` = `gz --versions` + dünya dosyası sha256 + URDF sha256.
3. Aynı seed + aynı `sim_version` → metriklerde ≤%2 sapma. Aşarsa koşu
   `deterministic=false` işaretlenir ve **evrim kararında kullanılmaz.**
4. Wall-clock'a bağlı hiçbir mantık kullanılmaz; yalnızca sim time.

### 11.3 Sim-to-real protokolü

**Referans manevra seti** (5 manevra, her biri 10 tekrar):

| Manevra | Komut | Ölçülen |
|---|---|---|
| `M1_straight` | 2 m düz, 0.2 m/s | Sapma (m), enerji (Wh), süre |
| `M2_turn` | 180° yerinde dönüş | Açı hatası (°), enerji |
| `M3_step` | 40 mm basamak | Başarı, max eklem torku |
| `M4_stand` | 30 s ayakta duruş | Gövde salınımı RMS (mm) |
| `M5_payload` | 500 g yük ile M1 | Sapma, enerji |

**Reality gap metriği:**

```
gap = mean_over_manevra( |sim_metrik − real_metrik| / real_metrik )
```

| gap | Anlam | Eylem |
|---|---|---|
| ≤ 0.10 | İyi | Normal çalışma |
| 0.10–0.20 | Kabul edilebilir | İzle |
| > 0.20 | Kalibre değil | **Evrim durdurulur**, fizik yeniden kalibre edilir |

**Kalibrasyon parametreleri:** sürtünme katsayısı, eklem damping, motor
kazancı, gövde eylemsizliği düzeltmesi, iletişim gecikmesi. Kalibrasyon
`scipy.optimize.least_squares` ile referans manevra verisine uydurulur.

### 11.4 Domain randomization

Her sim koşusunda aşağıdakiler ±%15 aralığında rastgeleleştirilir:

| Parametre | Nominal |
|---|---|
| Yüzey sürtünmesi | 0.7 |
| Link kütleleri | CAD değeri |
| IMU gürültü σ | 0.01 rad/s |
| Enkoder gürültü σ | 0.002 rad |
| Kontrol gecikmesi | 8 ms |
| Motor tork sabiti | Veri sayfası |

Yalnızca **randomize koşullarda dayanıklı** çözümler kabul edilir.

---

## 12. MEKANİK VE ÜRETİM

### 12.1 FreeCAD kullanımı (headless)

FreeCAD 1.0, `freecadcmd` ile başsız çalışır. Şablonlar Python'dur:

```python
# hardware/cad/templates/leg_link_v1.py
import FreeCAD as App, Part

SCHEMA = { ... }   # §4.3'teki JSON Schema

def build(p: dict, out_dir: str) -> dict:
    doc = App.newDocument("leg_link")
    body = Part.makeBox(p["length_mm"], p["width_mm"], p["height_mm"])
    # ... kaburgalar, delikler, filetolar — tamamı parametrik
    shape = body
    obj = doc.addObject("Part::Feature", "leg_link"); obj.Shape = shape
    doc.recompute()

    props = shape                       # kütle özellikleri
    result = {
        "volume_mm3": shape.Volume,
        "center_of_mass": tuple(shape.CenterOfMass),
        "inertia": shape.MatrixOfInertia.A,   # URDF için — §12.2
    }
    Part.export([obj], f"{out_dir}/leg_link.step")
    obj.Shape.exportStl(f"{out_dir}/leg_link.stl")
    return result
```

**Şablon kütüphanesi (Phase 6'ya kadar 5 şablon yeterlidir):**
`leg_link_v1`, `bracket_v1`, `foot_pad_v1`, `sensor_mount_v1`,
`battery_tray_v1`. Yeni şablon eklemek **insan işidir**, LLM işi değildir.

### 12.2 URDF üretimi — eylemsizlik kuralı

```python
# generators/urdf.py
mass_kg  = volume_mm3 * 1e-9 * density_kg_m3   # malzeme yoğunluğu
ixx, iyy, izz, ixy, ixz, iyz = from_freecad_inertia(result["inertia"], mass_kg)
```

**Kesin kurallar:**
- Eylemsizlik tensörü **her zaman** FreeCAD kütle özelliklerinden alınır.
  Mesh'ten tahmin **yasaktır**.
- `collision` mesh ≠ `visual` mesh. Collision için convex hull
  (`shape.makeConvexHull()`) veya primitif kullanılır.
- Her URDF üretiminden sonra otomatik kontroller:
  `check_urdf`, üçgen eşitsizliği (`ixx+iyy ≥ izz` vb.), kütle > 0,
  toplam kütle ölçülen değerin ±%10'unda.

### 12.3 DFM kuralları (otomatik, üretimden önce)

| Kural | Sınır | İhlalde |
|---|---|---|
| Minimum et kalınlığı | ≥ 1.2 mm | Ret |
| Destek gerektirmeyen açı | ≤ 45° | Uyarı + destek hesabı |
| Köprü uzunluğu | ≤ 10 mm | Ret |
| Minimum delik çapı | ≥ 2.0 mm | Ret |
| Katman yönüne dik ana yük | — | Uyarı (anizotropi) |
| En küçük detay | ≥ nozul çapı (0.4 mm) | Ret |
| Baskı hacmi | ≤ 250×210×220 mm | Ret |
| PA6-CF seçildiyse | Sertleştirilmiş nozul + kurutma + kapalı hazne | BOM'a otomatik ekle |

### 12.4 Üretim boru hattı

```
STEP/STL  →  3MF (PrusaSlicer profili ile)
   →  prusa-slicer --export-gcode  (CLI, alt süreç)
   →  prusa-gcodeviewer --export-png  (görsel doğrulama)
   →  otomatik G-code analizi (süre, filament, sıcaklık, katman)
   →  [ONAY seviye 4 — mobilde PNG ile]
   →  PrusaLink PUT /api/v1/files → POST /api/v1/job
   →  canlı takip (GET /api/v1/status → SignalR PrintProgress)
   →  Kalite kontrolü (§12.5)
   →  Montaj → genome güncelleme → fiziksel test
```

**Slicer profilleri:** `manufacturing/slicer_profiles/`
`petg_0.20_structural.ini`, `pa6cf_0.20_structural.ini`,
`pla_0.25_draft.ini`, `asa_0.20_outdoor.ini`.

### 12.5 Kalite kontrolü (mobilde form olarak girilir)

| Kontrol | Yöntem | Eşik |
|---|---|---|
| Kritik boyutlar (3 nokta) | Kumpas | ±0.3 mm |
| Delik çapı | Pin gauge | Geçer/geçmez |
| Kütle | Terazi | CAD tahmininin ±%5'i |
| Katman yapışması | Görsel + elle bük | Ret/kabul |
| Warp | Düz yüzey + ışık | ≤ 0.5 mm |

Sapma sistematikse (3 ardışık parçada aynı yön) slicer kompanzasyonu
otomatik güncellenir ve `audit_log`'a yazılır.

---

## 13. ELEKTRONİK VE HARDWARE GENOME

### 13.1 KiCad kapsam sınırı

**İzinli:** 2 katman, ≥0603 SMD ve THT, <10 MHz dijital, 5 V/12 V güç
dağıtımı, sensör breakout, konnektör kartı.
**Yasak:** çok katman, empedans kontrollü, RF, sıfırdan anahtarlamalı güç,
>10 A, >48 V. Bu sınıflar için **hazır modül** kullanılır.

### 13.2 Doğrulama zinciri

```
Şablon + parametre → şematik (kicad-cli sch)
  → ERC (0 hata zorunlu)
  → ngspice güç yolu simülasyonu (gerilim düşümü <%5, seviye uyumu)
  → PCB layout (şablon yerleşim)
  → DRC — üretici kural dosyası ile (JLCPCB/PCBWay .kicad_dru)
  → 3D çakışma kontrolü
  → BOM + stok/fiyat kontrolü
  → [İNSAN GÖZDEN GEÇİRME — atlanamaz]
  → gerber export → sipariş
```

**İnsan gözden geçirme neden zorunlu:** LLM'ler şematikte sessiz hata yapar
(ters polarite, eksik decoupling, yanlış pinout, floating enable, eksik
pull-up). PCB siparişi geri alınamaz ve 2-3 hafta kaybettirir.

### 13.3 Hardware Genome şeması

```yaml
schema_version: 1
genome_id: quadruped_v2
hash: a3f91c7                      # içerikten türetilir
parent: quadruped_v1@8e2bd40
created: 2026-02-08
status: active                     # draft | testing | active | deprecated

morphology:
  body_type: quadruped
  leg_count: 4
  dof_per_leg: 4
  total_dof: 16

mechanical:
  material: PA6-CF
  material_density_g_cm3: 1.17
  body_mass_kg: 2.40               # ÖLÇÜLEN
  body_mass_cad_kg: 2.31           # TAHMİN
  cad_templates:
    leg_link: {template: leg_link_v1, params: {length_mm: 120, width_mm: 28, wall_mm: 2.0, rib_count: 3}}
    foot_pad: {template: foot_pad_v1, params: {diameter_mm: 32, wall_mm: 2.4, material: TPU}}
  param_ranges:                    # evrim arama uzayı
    leg_link.length_mm: [100, 145]
    leg_link.wall_mm:   [1.6, 3.2]
    leg_link.rib_count: [0, 5]

electronics:
  compute:           {model: raspberry_pi_5_8gb}
  motion_controller: {model: stm32f446, firmware: firmware/stm32_motion@v1.4.2}
  aux_mcu:           {model: esp32s3,   firmware: firmware/esp32_aux@v1.1.0}
  safety_mcu:        {model: atmega328p,firmware: firmware/safety_watchdog@v1.0.3}
  actuators: {model: sts3215, count: 16, stall_torque_nm: 2.9}
  sensors:
    - {type: imu,          model: bno085, rate_hz: 100}
    - {type: depth_camera, model: realsense_d405, rate_hz: 15}
    - {type: current,      model: ina226, count: 2}

power:
  battery: {chemistry: lipo, cells: 4, capacity_mah: 5200, c_rating: 25}
  bms: required
  rails:
    - {v: 5.0, a_max: 5.0, converter: buck_5v5a}
    - {v: 3.3, a_max: 2.0, converter: ldo_3v3}

limits:                            # L4 DEĞİŞTİREMEZ — kod ile korunur
  joint_torque_nm_max: 2.5
  joint_velocity_rads_max: 6.0
  body_current_a_max: 20.0
  body_temp_c_max: 70.0

manufacturing:
  print_time_h: 18.5
  material_cost_try: 640
  bom_cost_try: 9800               # ilk tedarikten sonra güncellenir
  assembly_time_h: 4.0

performance:                       # ÖLÇÜLEN, sim değil
  max_speed_mps: 0.42
  endurance_min: 34
  mtbf_h: 11.2

fitness:
  score: 0.7140
  campaign: campaign_003
  weights_ref: evolution/experiments/campaign_003/weights.yaml
```

**Kurallar:** `limits` bloğu evrim döngüsüne kapalıdır (kod ile zorlanır);
`hash` her artefaktta referans verilir; `parent` soy ağacını kurar;
JSON Schema doğrulaması CI'da zorunludur.

---

## 14. OTONOM ÇALIŞMA DÖNGÜSÜ

Bu bölüm "sürekli çalışsın, yeni görevler bulsun, kendini geliştirsin"
gereksiniminin tam spesifikasyonudur.

### 14.1 Ana döngü (systemd servisi, 7/24)

```python
# brain/neml_brain/autonomy/loop.py
async def autonomy_loop():
    while True:
        await safety_preflight()            # L0 kontrolleri, robot durumu
        if not await budget_ok():           # §14.4
            await sleep_until_budget_reset(); continue

        await discover_tasks()              # §14.2 — yeni görev üret
        task = await pick_next_task()       # öncelik sıralı
        if task is None:
            await idle_policy()             # §14.5
            continue

        await execute(task)                 # LangGraph
        await record_and_learn(task)        # §14.6
        await asyncio.sleep(TICK_S)         # TICK_S = 5
```

### 14.2 Görev keşfi — beş kaynak

| Kaynak | Tetik | Üretilen görev |
|---|---|---|
| **Başarısızlık onarımı** | Bir skill'in son 20 koşusunda başarı < %70 | `repair`: başarısızlık modunu hedefleyen parametre araması |
| **Kapsam boşluğu** | Bir dünya/ön koşul kombinasyonu hiç denenmemiş veya >14 gündür denenmemiş | `exploration`: o kombinasyonda sim koşusu |
| **Evrim kampanyası** | Aktif kampanya var, nesil tamamlanmamış | `evolution`: aday üret + değerlendir |
| **Bakım** | Son kalibrasyondan >7 gün, gap >0.15, veya MTBF eşiği | `maintenance` / `calibration` |
| **İnsan** | Mobil/web'den gelen komut | `human` — her zaman en yüksek öncelik |

**Öncelik formülü:**

```
P = 100·is_human
  + 40·urgency          (0-1: batarya/arıza/deadline yakınlığı)
  + 25·expected_gain    (0-1: tahmini fitness artışı)
  + 15·staleness        (0-1: son denemeden bu yana geçen süre / 14 gün)
  + 10·cheapness        (0-1: 1 − tahmini kaynak / bütçe)
  − 50·blocked          (onay bekliyor veya bağımlılık eksik)
```

Kuyruk `P DESC` sıralanır, eşitlikte `created_at ASC`.

### 14.3 Kendini geliştirme döngüsü (fitness tam tanımı)

```
F = 0.40·normalize(görev_başarısı)          [0-1, yüksek iyi]
  + 0.15·normalize(1 / enerji_Wh)           [ters normalize]
  + 0.15·normalize(1 / kütle_kg)            [ters normalize]
  + 0.15·normalize(dayanıklılık_MTBF_h)
  − 0.10·normalize(üretim_maliyeti_TRY)
  − 0.05·normalize(üretim_süresi_h)
  − P_ihlal
```

- **Ağırlıklar kampanya başında sabitlenir**, `campaigns.weights` alanına
  yazılır ve kampanya boyunca **değiştirilemez** (DB trigger ile korunur).
  Sonucu gördükten sonra ağırlık değiştirmek sonucu geçersiz kılar.
- `normalize(x)` = mevcut aktif genome'un değerine göre min-max ölçekleme,
  [0,1] aralığına kırpılır.
- `P_ihlal` sert cezadır: `limits` ihlali, DFM reddi, DRC hatası veya
  montaj arayüzü değişikliği → `F = −1` (kabul edilemez, düşük puanlı değil).

**Arama operatörleri:**

| Operatör | Pay | Uygulama |
|---|---|---|
| `mutation` | %50 | `param_ranges` içindeki bir sürekli parametrede ±%10 |
| `crossover` | %20 | İki üst adayın modül düzeyinde birleşimi |
| `llm_guided` | %25 | Başarısızlık analizinden hedefli değişiklik + gerekçe |
| `seed` | %5 | Rastgele yeniden başlatma (yerel minimumdan çıkış) |

`llm_guided` adayların gerekçesi kaydedilir ve sonuçla karşılaştırılır.
Gerekçesi 3 kez tutmayan hipotez türünün payı %5'e düşürülür (basit
bandit ağırlıklandırma).

**Kabul kriteri (5 şart, hepsi zorunlu):**

1. Sim fitness'ı mevcut aktif genome'dan yüksek — n ≥ 20 randomize koşu,
   bootstrap %95 GA örtüşmüyor
2. Reality gap ≤ 0.20
3. Regresyon yok — mevcut tüm `validated` skill'ler hâlâ ≥ eski başarı − %5
4. Bütçe içinde (maliyet + süre)
5. İnsan onayı (seviye 4)

Herhangi biri sağlanmazsa → **rollback**: önceki genome `active` kalır,
aday `rejected` işaretlenir, gerekçe kaydedilir.

### 14.4 Bütçe sistemi (günlük, 00:00 TRT sıfırlanır)

| Kaynak | Limit | Aşımda |
|---|---|---|
| GPU süresi (vLLM + visual sim) | 6 saat | Yeni LLM çağrısı reddedilir, kuyruk bekler |
| Simülasyon koşusu | 200 | Yeni sim reddedilir |
| Fiziksel robot çalışma | 3 saat | Sadece sim görevleri |
| Filament | 500 g | Baskı onayı reddedilir |
| PCB siparişi | 1 / ay | Onay reddedilir |
| LLM token | 500.000 | Reddedilir |

Bütçe durumu `/v1/budget` ve mobil panelde çubuk olarak gösterilir.
%90'da bildirim gider.

### 14.5 Boşta kalma politikası

Kuyrukta görev yoksa, sırayla:

1. Robot bataryası < %30 → şarj istasyonuna gönder, `charging`
2. Kapsam boşluğu var mı → `exploration` görevi üret
3. Aktif kampanya var mı → bir sonraki nesli üret
4. Kalibrasyon eskimiş mi → `calibration` görevi üret
5. Hiçbiri yoksa → `memory` konsolidasyonu: son 24 saatin başarısızlık
   loglarını chunk'la, gömle, `memory_chunks`'a yaz
6. O da bittiyse → 60 s uyku

**Kural:** Sistem asla "boşta bekleme" durumunda kalmaz ama asla bütçe
dışına da çıkmaz. Boşluk, ucuz sim işiyle doldurulur; pahalı fiziksel iş
yalnızca planlı olarak yapılır.

### 14.6 Öğrenme kaydı

Her görev sonrası:

1. Sonuç `task_runs`'a yazılır
2. Başarısızlıksa `failure_tag` profili ile mod etiketlenir
3. Etiket + bağlam chunk'lanıp gömülür → `memory_chunks`
4. Skill'in kümülatif başarı istatistiği güncellenir
5. Başarı < %70'e düşerse otomatik `repair` görevi üretilir (§14.2)

---

## 15. REPOSITORY YAPISI

```
neml/
├─ README.md                    # bu dosyanın kısa özeti
├─ NEML_SPEC.md                 # bu dosya — implementasyon kontratı
├─ LICENSE                      # §1.2
├─ SAFETY.md                    # §5 — fiziksel çalışma öncesi okunur
├─ CHANGELOG.md
├─ .pre-commit-config.yaml      # telif başlığı, ruff, mypy, bandit
│
├─ docs/
│  ├─ adr/                      # mimari karar kayıtları (ADR-001…)
│  ├─ runbooks/                 # olay müdahale prosedürleri
│  └─ api/                      # OpenAPI çıktıları
│
├─ config/
│  ├─ llm.yaml  mcp.yaml  budget.yaml  gz_bridge.yaml
│  ├─ policy/tools.yaml
│  └─ profiles/
│
├─ docker/
│  ├─ compose.yml               # tüm yığın
│  ├─ vllm/  brain/  embed/  sandbox/  postgres/
│
├─ brain/                       # Python — §8.2
│  ├─ pyproject.toml
│  ├─ neml_brain/
│  └─ tests/
│
├─ mcp_servers/
│  ├─ neml_mcp_sim/  neml_mcp_fab/  neml_mcp_genome/  neml_mcp_cad/
│  └─ vendor/                   # dışarıdan kurulanların config'i (kod değil!)
│
├─ ros2_ws/src/
│  ├─ neml_msgs/                # özel mesaj/servis/aksiyon
│  ├─ neml_description/         # URDF/xacro + meshes (git-lfs)
│  ├─ neml_bringup/             # launch dosyaları
│  ├─ neml_control/             # ros2_control konfigürasyonu
│  ├─ neml_safety/              # L0/L1 köprüsü, watchdog izleyici
│  ├─ neml_perception/
│  ├─ neml_swarm/               # koordinatör
│  └─ neml_sim/                 # dünyalar, gz launch
│
├─ firmware/
│  ├─ stm32_motion/             # micro-ROS, 1 kHz
│  ├─ esp32_aux/                # micro-ROS, telemetri
│  └─ safety_watchdog/          # ATmega328P, bağımsız
│
├─ hardware/
│  ├─ cad/templates/            # FreeCAD parametrik şablonlar (§12.1)
│  ├─ exports/                  # STEP/STL/3MF — git-lfs
│  ├─ electronics/              # KiCad projeleri
│  └─ genome/                   # genome yaml + json-schema
│
├─ evolution/
│  ├─ search/  fitness/
│  └─ experiments/campaign_XXX/ # weights.yaml, seeds, sonuçlar
│
├─ manufacturing/
│  ├─ slicer_profiles/          # *.ini
│  └─ jobs/
│
├─ dotnet/                      # §9.1
│
├─ mobile/                      # Flutter — §10
│  ├─ lib/{core,features,shared}/
│  └─ test/
│
├─ scripts/
│  ├─ setup/  db/  calibration/  release/
│
└─ data/                        # git'te DEĞİL — .gitignore
```

**git-lfs izlenen uzantılar:** `*.stl *.step *.3mf *.gcode *.png *.mp4 *.bag *.FCStd`

---

## 16. UYGULAMA GÖREV LİSTESİ (AGENT İÇİN)

Sıralıdır. Her görevin kabul kriteri karşılanmadan sonrakine geçilmez.
Süre tahminleri tek geliştirici + agent varsayımıyla verilmiştir.

### Faz 0 — Temel (2 hafta)

| ID | Görev | Kabul kriteri |
|---|---|---|
| T-001 | Repo iskeleti, LICENSE, telif hook'u, .gitignore, git-lfs | `pre-commit run --all` yeşil, her dosyada telif başlığı |
| T-002 | Ubuntu 24.04 + ROS 2 Jazzy + Gazebo Harmonic kurulumu | `ros2 doctor` temiz, `gz sim --versions` çalışıyor |
| T-003 | PostgreSQL 16 + pgvector, §7 şeması, Alembic migration | `alembic upgrade head` başarılı, tüm tablolar mevcut |
| T-004 | Docker compose: postgres, vllm, embed, brain iskeleti | `docker compose up` tüm servisler `healthy` |
| T-005 | vLLM 3 GB konfigürasyonu, model indirme | `/v1/models` yanıt veriyor, VRAM < 3 GB, ilk token < 2 s |
| T-006 | CPU embedding servisi | 100 chunk/3 s, 384 boyut doğru |
| T-007 | CI (GitHub Actions veya yerel): lint, test, şema doğrulama | Boş PR'da CI yeşil |

### Faz 1 — Beyin (4 hafta)

| ID | Görev | Kabul kriteri |
|---|---|---|
| T-010 | `LLMProvider` + `VllmProvider` (classify/fill/summarize) | Şema dışı çıktı üretilemiyor (100 rastgele testte 0 ihlal) |
| T-011 | Prompt profilleri (§4.4), 6 profil + şemalar | Her profil için birim test |
| T-012 | LangGraph orkestratör + PostgreSQL checkpointer | Süreç öldürülüp yeniden başlatıldığında akış devam ediyor |
| T-013 | 4 çekirdek agent (orchestrator, planner, coding, memory) | Her agent için girdi/çıktı şeması + izinli araç listesi tanımlı |
| T-014 | Politika motoru (§5.4) | Yasaklı araç çağrısı 100/100 reddediliyor, audit'e yazılıyor |
| T-015 | Sandbox (§5.3) | Ağ erişimi denemesi başarısız, timeout çalışıyor, kaynak limitleri etkin |
| T-016 | MCP istemci katmanı + filesystem/git/postgres sunucuları | `/health` tüm MCP'leri yeşil raporluyor |
| T-017 | FastAPI REST (§8.3) + OpenAPI | Tüm endpoint'ler için sözleşme testi |
| T-018 | Bütçe sistemi (§14.4) | Limit aşımında istek reddi + doğru hata kodu |
| T-019 | Audit log + structlog JSON + Prometheus metrikleri | Her araç çağrısı loglanıyor |
| T-020 | `nemlctl` Python CLI | `nemlctl status/task/campaign/approve` çalışıyor |

### Faz 2 — Simülasyon (4 hafta)

| ID | Görev | Kabul kriteri |
|---|---|---|
| T-030 | `neml_description`: tek robot URDF/xacro | `check_urdf` temiz, inertia CAD kaynaklı, collision ≠ visual |
| T-031 | FreeCAD şablon motoru + 5 şablon (§12.1) | Her şablon STEP+STL+kütle özellikleri üretiyor, 20 rastgele parametrede 0 hata |
| T-032 | DFM doğrulayıcı (§12.3) | Bilinen 10 kötü parametre setinin 10'u da reddediliyor |
| T-033 | `neml-mcp-sim` (§6.3) | Tüm fonksiyonlar tipli, timeout'lu |
| T-034 | 5 Gazebo dünyası + `ros_gz` köprüsü | Headless koşuyor, sensör verisi ROS 2'ye akıyor |
| T-035 | GPU mutex (§4.5) | `visual` profilde vLLM duruyor/başlıyor, yarış koşulu yok |
| T-036 | Determinizm testi | Aynı seed 10 koşu, metrik sapması ≤ %2 |
| T-037 | Domain randomization (§11.4) | Parametreler seed'den türetiliyor, kayıt altında |
| T-038 | Regresyon paketi altyapısı | `pytest -m regression` tüm skill'leri koşuyor |

### Faz 3 — Uzak API + Mobil (5 hafta)

| ID | Görev | Kabul kriteri |
|---|---|---|
| T-050 | .NET 9 çözüm iskeleti + EF Core + migration | `dotnet test` yeşil, DB oluşuyor |
| T-051 | Auth (JWT + refresh + Argon2 + roller) | Yetkisiz erişim 401/403, token rotasyonu çalışıyor |
| T-052 | REST controller'lar (§9.3) | Swagger tam, her endpoint entegrasyon testli |
| T-053 | SignalR `LiveHub` + gruplar (§9.4) | 3 eşzamanlı istemci, olay kaybı yok |
| T-054 | `cloud-bridge` (Python tarafı, WSS client) | Bağlantı kopup dönüyor, kuyruk boşalıyor, idempotency çalışıyor |
| T-055 | Bridge sunucu tarafı + komut kuyruğu | Komut → lab → ack tur süresi < 2 s (normal ağ) |
| T-056 | Blazor WASM web arayüzü (panel + görev + onay) | Mobil ile aynı veriyi gösteriyor |
| T-057 | `Neml.Cli` konsol aracı | Görev/onay/durum işlemleri çalışıyor |
| T-058 | Flutter iskelet + auth + go_router + Riverpod | Giriş → panel akışı çalışıyor |
| T-059 | Flutter ekranlar 2-5 (panel, robot, görevler) | Canlı telemetri akıyor, grafik 60 s pencere |
| T-060 | Flutter ekran 6 (beyin konsolu) | Komut gönderiliyor, niyet + sonuç gösteriliyor |
| T-061 | Flutter ekranlar 7-9 (evrim, genome, skill) | Fitness eğrisi doğru çiziliyor |
| T-062 | Flutter ekran 10 (onaylar) + FCM push | Push geliyor, seviye 4 metin doğrulaması çalışıyor |
| T-063 | Flutter ekranlar 11-13 + çevrimdışı önbellek | Uçak modunda son durum görünüyor, yazma engelleniyor |

### Faz 4 — Gerçek Robot (6 hafta)

| ID | Görev | Kabul kriteri |
|---|---|---|
| T-070 | Mekanik montaj + BOM tedariki | Ölçülen kütle CAD'in ±%10'unda |
| T-071 | `safety_watchdog` firmware (ATmega328P) | 150 ms heartbeat kaybında röle açılıyor — osiloskopla doğrulandı |
| T-072 | `stm32_motion` firmware + micro-ROS | 1 kHz döngü, tork limiti derleme sabiti |
| T-073 | `esp32_aux` firmware | Telemetri 10 Hz, ROS 2'de görünüyor |
| T-074 | `neml_safety` ROS 2 paketi | E-stop olayı < 50 ms'de tüm yığına yayılıyor |
| T-075 | E-stop + watchdog kabul testi | `safety_checks` kaydı var, test videosu arşivde |
| T-076 | Kalibrasyon scriptleri (§11.3) | 5 referans manevra otomatik koşuyor |
| T-077 | Reality gap ölçümü ve fizik kalibrasyonu | gap ≤ 0.20 |
| T-078 | Dağıtım kapıları (seviye 1-3) uçtan uca | Onaysız fiziksel görev başlatılamıyor |

### Faz 5 — Swarm + Otonomi (4 hafta)

| ID | Görev | Kabul kriteri |
|---|---|---|
| T-080 | İkinci ve üçüncü robot | 3 robot aynı anda `idle` |
| T-081 | `rmw_zenoh` + QoS profilleri (§17.2) | 3 robot, 30 dk kesintisiz, paket kaybı < %1 |
| T-082 | `neml_swarm` koordinatörü | Bir robot kapatıldığında görev diğerlerine devrediliyor |
| T-083 | Bağlantı kaybı davranışı | Robot 2 s içinde güvenli duruma geçiyor |
| T-084 | Otonomi döngüsü (§14.1) | 72 saat kesintisiz çalışma, bütçe aşımı yok |
| T-085 | Görev keşfi (§14.2) beş kaynak | Her kaynaktan en az 1 görev otomatik üretildi |
| T-086 | Boşta kalma politikası (§14.5) | Boş kuyrukta sistem anlamlı iş üretiyor |

### Faz 6 — Evrim (6 hafta)

| ID | Görev | Kabul kriteri |
|---|---|---|
| T-090 | Fitness motoru (§14.3) + ağırlık kilidi | Kampanya başladıktan sonra ağırlık değiştirilemiyor (DB trigger testi) |
| T-091 | Arama operatörleri + seçilim | 20 adaylık nesil sim'de tamamlanıyor |
| T-092 | Kabul kriteri + rollback | Reddedilen aday sonrası eski genome aktif kalıyor |
| T-093 | KiCad şablon motoru + doğrulama zinciri (§13.2) | ERC/DRC 0 hata, BOM üretiliyor |
| T-094 | `neml-mcp-fab` + PrusaSlicer + G-code Viewer | Dilimleme + PNG önizleme + tahmin çalışıyor |
| T-095 | PrusaLink entegrasyonu + canlı takip | Baskı ilerlemesi mobilde görünüyor |
| T-096 | Kalite kontrol formu + genome geri yazımı | Ölçüm girildi, genome güncellendi |
| T-097 | **Uçtan uca evrim testi** | Bir parça: hipotez → CAD → sim → onay → baskı → montaj → ölçüm → fitness artışı istatistiksel olarak doğrulandı |

**Toplam tahmini süre: 31 hafta.** Fazlar paralelleştirilemez —
her faz bir öncekinin kabul kriterine dayanır. Tek istisna: Faz 3 (mobil/API)
Faz 2 ile paralel yürütülebilir (farklı yığın, bağımlılık yok).

---

## 17. ORTAM, PORTLAR, KURULUM

### 17.1 Portlar

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

### 17.2 ROS 2 / ağ ayarları

```bash
export ROS_DOMAIN_ID=42
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
export ZENOH_ROUTER_CONFIG_URI=/srv/neml/config/zenoh_router.json5
```

**QoS profilleri:**

| Topic sınıfı | Reliability | Durability | History |
|---|---|---|---|
| `/*/telemetry/*` | BEST_EFFORT | VOLATILE | KEEP_LAST(1) |
| `/*/cmd/*` | RELIABLE | VOLATILE | KEEP_LAST(10) |
| `/*/state` | RELIABLE | TRANSIENT_LOCAL | KEEP_LAST(1) |
| `/*/camera/*` | BEST_EFFORT | VOLATILE | KEEP_LAST(1) |

**Kural:** Kamera akışı ham olarak swarm ağına verilmez; robot üzerinde
JPEG sıkıştırılır ve yalnızca talep üzerine gönderilir.

### 17.3 Ortam değişkenleri (`.env.example`)

```bash
# --- Lab ---
NEML_ENV=lab
NEML_DB_URL=postgresql+asyncpg://neml:CHANGEME@localhost:5432/neml_local
NEML_VLLM_URL=http://localhost:8000/v1
NEML_EMBED_URL=http://localhost:8081
NEML_MODEL=Qwen/Qwen2.5-Coder-1.5B-Instruct-AWQ
NEML_WORK_DIR=/srv/neml/work
NEML_ARTIFACT_DIR=/srv/neml/artifacts
NEML_OUTBOX_DB=/var/lib/neml/outbox.db
HF_TOKEN=CHANGEME

# --- Bridge ---
NEML_CLOUD_WS=wss://api.neml.example.com/bridge/ws
NEML_NODE_ID=lab-01
NEML_API_KEY=CHANGEME

# --- Yazıcı ---
PRUSALINK_URL=http://192.168.1.50
PRUSALINK_API_KEY=CHANGEME
PRUSASLICER_BIN=/usr/bin/prusa-slicer
PRUSA_GCODEVIEWER_BIN=/usr/bin/prusa-gcodeviewer

# --- Uzak sunucu (.NET) ---
ConnectionStrings__Default=Host=localhost;Database=neml_cloud;Username=neml;Password=CHANGEME
Jwt__Issuer=neml
Jwt__Audience=neml-clients
Jwt__Key=CHANGEME_MIN_32_CHARS
Fcm__CredentialsPath=/etc/neml/fcm.json
```

### 17.4 Kurulum sırası

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

---

## 18. TEST, CI VE GÖZLEMLENEBİLİRLİK

### 18.1 Test piramidi

| Seviye | Araç | Sıklık | Kapsam hedefi |
|---|---|---|---|
| Birim (Python) | pytest | Her commit | %80 |
| Birim (.NET) | xUnit | Her commit | %75 |
| Birim (Flutter) | flutter_test | Her commit | %60 |
| Şema | JSON Schema + pydantic | Her commit | %100 |
| Entegrasyon | testcontainers | Her commit | Kritik yollar |
| ROS 2 launch | launch_testing | Her commit | Tüm bringup |
| Sim regresyon | pytest -m regression | Her PR | Tüm validated skill |
| Donanım-in-the-loop | Elle + script | Her sürüm | Güvenlik testleri |
| Saha | Elle | Faz çıkışı | Tam görev |

### 18.2 CI kapıları (hepsi bloklayıcı)

1. `ruff check` + `mypy --strict` + `bandit`
2. `dotnet format --verify-no-changes` + `dotnet test`
3. `flutter analyze` + `flutter test`
4. Telif başlığı kontrolü (her yeni dosyada)
5. Genome JSON Schema doğrulaması
6. URDF doğrulama + eylemsizlik makullük testi
7. Sim regresyon paketi
8. Lisans taraması — **GPL/AGPL kodun ağaca girmediği doğrulanır** (§1.3)
9. Sır taraması (`gitleaks`)

### 18.3 Gözlemlenebilirlik

| Sinyal | Araç | Saklama |
|---|---|---|
| Log | structlog JSON → `journald` → Loki (opsiyonel) | 30 gün |
| Metrik | Prometheus `:8080/metrics` + node_exporter | 90 gün |
| Panel | Grafana (lab içi) | — |
| Robot kayıt | rosbag2 | 30 gün (başarısızlıklar kalıcı) |
| Denetim | `audit_log` tablosu | 2 yıl |
| Deney | `evolution/experiments/` + git | Süresiz |

**Zorunlu metrikler:** `neml_llm_requests_total`, `neml_llm_latency_seconds`,
`neml_gpu_lock_wait_seconds`, `neml_sim_runs_total`,
`neml_task_queue_depth`, `neml_budget_used_ratio`,
`neml_bridge_connected`, `neml_robot_battery_soc`,
`neml_approval_pending_count`, `neml_safety_check_age_hours`.

---

## 19. RİSKLER VE AZALTMA

| # | Risk | Olasılık | Etki | Azaltma | Tetikte eylem |
|---|---|---|---|---|---|
| 1 | 1.5B model parametre doldurmada bile yetersiz | Orta | Yüksek | §4.3 kısıtlı üretim; şema zaten geçerli çıktı garantiler | Parametreleri elle doldur, model yalnızca router olarak kalsın |
| 2 | 3 GB GPU vLLM + Gazebo için yetersiz | Yüksek | Orta | §4.5 mutex, `fast` profil varsayılan | Simülasyonu tamamen CPU'ya al, kamera skill'lerini Faz 6'ya ertele |
| 3 | Reality gap kapanmıyor | Orta | Yüksek | §11.3 kalibrasyon | Yalnızca yazılım evrimi yap, donanım evrimini durdur |
| 4 | MCP depolarının ölü/olmaması | Orta | Düşük | §6.2 kendi sunucu spec'leri hazır | Kendi sunucunu yaz (~400 satır) |
| 5 | AI üretimi tasarımın donanıma zarar vermesi | Düşük | Çok yüksek | §5 L0 + dağıtım kapıları | Sistemi durdur, olay incelemesi, `SAFETY.md` güncelle |
| 6 | Kapsam genişlemesi, faz tamamlanmaması | Yüksek | Yüksek | §16 kabul kriterleri | Kriter karşılanmadan ilerleme yasak |
| 7 | WiFi'de swarm gecikmesi | Orta | Orta | Zenoh + QoS (§17.2) | 5 GHz ayrı SSID, kamera akışını kes |
| 8 | PA6-CF baskı tutarsızlığı | Orta | Düşük | Kurutucu + kapalı hazne | PETG'ye düş |
| 9 | PCB revizyon maliyeti/süresi | Orta | Orta | Ayda 1 sipariş bütçesi | Hazır modül kullan |
| 10 | Telemetri hacmi | Orta | Düşük | Partisyon + downsampling (§7) | Saklama süresini kısalt |
| 11 | Uzak sunucu güvenlik ihlali | Düşük | Yüksek | JWT + API key + IP kısıt + oran sınırı; sunucu robotu doğrudan kontrol edemez, yalnızca kuyruğa yazar | Anahtarları döndür, bridge'i kapat |
| 12 | Fikri mülkiyet sızıntısı | Düşük | Yüksek | Özel repo, §1.2 lisans, sır taraması, GPL izolasyonu | Erişim denetimi, hukuki destek |

---

## 20. SÖZLÜK

| Terim | Anlam |
|---|---|
| **Genome** | Bir robot sürümünün tam makine-okunur tanımı (§13.3) |
| **Skill** | Doğrulanmış, sürümlü bir davranış (BT + parametreler + istatistik) |
| **Candidate** | Evrim döngüsünde henüz kabul edilmemiş genome varyantı |
| **Campaign** | Sabit ağırlık ve bütçeyle yürütülen bir evrim kampanyası |
| **Reality gap** | Sim ve gerçek ölçüm arasındaki normalize fark (§11.3) |
| **Dağıtım kapısı** | Fiziksel etki öncesi zorunlu insan onayı (§5.2) |
| **GPU mutex** | vLLM ile Gazebo'nun aynı anda GPU kullanmasını engelleyen kilit |
| **Kısıtlı üretim** | LLM'in yalnızca şema-uyumlu JSON üretmesi (§4.3) |
| **Bridge** | Lab'dan uzak sunucuya giden kalıcı WSS bağlantısı (§3.1) |
| **L0-L4** | Katman numaraları: L0 donanım güvenliği … L4 LLM |

---

## 21. BAŞARI TANIMI

> Sistem, bir robot revizyonunu insan tasarım müdahalesi olmadan üretip,
> iyileşmeyi fiziksel ölçümle istatistiksel olarak kanıtlayabiliyorsa
> NEML çalışıyordur. Kanıt yoksa, üretilen şey tasarım değil gürültüdür.

Ölçülebilir hali: **T-097 kabul kriteri.**

---

*Copyright (c) 2026 Mustafa Gulsoy.*
