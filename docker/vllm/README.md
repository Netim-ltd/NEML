<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# vLLM — 3 GB VRAM konfigürasyonu

Bu dizinde Dockerfile yoktur: `vllm/vllm-openai:latest` imajı olduğu gibi
kullanılır, servis tanımı `docker/compose.yml` içindedir. Burada yalnızca **neden
o parametreler** olduğu anlatılır. Parametreler NEML_SPEC.md §4.2'den birebir
alınmıştır; **değiştirilemez**, tartışmaya kapalıdır.

## 1. Kısıt: 3 GB VRAM (§4.1)

3 GB VRAM ile çalışabilecek model sınıfı **1.5B parametre, 4-bit kuantize**dir.
Bu boyuttaki bir model şunları **yapamaz**:

- Sıfırdan doğru FreeCAD Python scripti yazmak
- Şematik topolojisi tasarlamak
- Uzun bağlamlı mimari kararlar almak
- Güvenilir serbest-biçimli araç seçimi (tool calling) yapmak

Bu bir eksiklik değil, **tasarım girdisidir**. Mimari buna göre kurulmuştur:
model yalnızca sınıflandırır (`guided_choice`) ve parametre doldurur
(`guided_json`); üretimi deterministik şablon motorları yapar (§4.3). Bu yüzden
model küçüklüğü doğruluk riskini artırmaz — yanlış parametre simülasyonda elenir,
geçersiz geometri hiç üretilmez.

## 2. Parametre gerekçeleri (§4.2)

| Parametre | Değer | Neden |
|---|---|---|
| `--enforce-eager` | açık | CUDA graph belleği ~300-500 MB tasarruf |
| `--max-model-len` | 4096 | KV cache 3 GB'a sığsın |
| `--max-num-seqs` | 2 | Eşzamanlı istek belleği sınırlı |
| `--gpu-memory-utilization` | 0.88 | Sürücü/görüntü için pay bırak |
| `--guided-decoding-backend` | xgrammar | §4.3 için zorunlu |

Tabloda olmayan üç bayrak da aynı kısıttan gelir:

| Parametre | Değer | Neden |
|---|---|---|
| `--model` | `Qwen/Qwen2.5-Coder-1.5B-Instruct-AWQ` | §4.2'nin tek yerleşik modeli |
| `--quantization` | `awq` | 4-bit ağırlık; 3 GB'a sığmanın tek yolu |
| `--dtype` | `half` | Aktivasyonlar FP16; FP32 belleğe sığmaz |
| `--swap-space` | `2` | 2 GB CPU takas alanı; VRAM taşmasında kuyruk ölmesin |
| `--disable-log-requests` | açık | İstem içeriği log'a düşmez (§5.4 sır hijyeni) |

**Model seçimi:** `Qwen2.5-Coder-1.5B-Instruct-AWQ` tek yerleşik modeldir.
İkinci model **yüklenmez** — bellek yok. Farklı görevler ayrı model ile değil,
prompt profili ile ayrılır (§4.4: `router`, `param_mech`, `param_elec`,
`param_skill`, `failure_tag`, `summarize`).

## 3. Yedek model (daha da kısıtlı donanım)

`Qwen2.5-0.5B-Instruct` — yalnızca sınıflandırma ve yönlendirme yapabilir,
**parametre üretemez**. Bu modele düşüldüğünde §4.3'teki `param_fill` adımı elle
doldurulur; boru hattının geri kalanı (deterministik üretim, DFM/DRC doğrulama,
onay kapıları) değişmez. Geçiş `config/llm.yaml` ve `NEML_MODEL` ile yapılır,
kod değişmez.

## 4. GPU çakışması (§4.5)

3 GB'ı vLLM ve Gazebo aynı anda kullanamaz. Varsayılan simülasyon profili
`fast`'tir ve CPU'da render eder; vLLM çalışmaya devam eder. Yalnızca `visual`
profilinde orkestratör `neml-vllm` konteynerini Docker soketi üzerinden durdurur,
simülasyonu koşar, sonra başlatır (~40 s; bu maliyet planlamaya dahildir).
Konteyner adının `neml-vllm` olması bu yüzden zorunludur —
`brain/neml_brain/runtime/gpu_lock.py` bu adı durdurur.

## 5. Doğrulama (T-005)

```bash
docker compose --env-file .env -f docker/compose.yml up -d vllm
curl localhost:8000/v1/models        # model listesi dönmeli
nvidia-smi --query-gpu=memory.used --format=csv   # < 3 GB
```

Kabul kriteri: `/v1/models` yanıt veriyor, VRAM < 3 GB, ilk token < 2 s.
İlk açılış ağırlıkları indirir (`hf-cache` adlı Docker volume'una); bu yüzden
`healthcheck` içinde `start_period: 900s` vardır.
