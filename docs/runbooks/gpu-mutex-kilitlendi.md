<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Runbook — GPU mutex kilitlendi

**Kaynak:** NEML_SPEC.md §4.5, §4.1 · **Önem:** Orta

3 GB VRAM'i vLLM ve Gazebo aynı anda kullanamaz. `GpuLock` tek tüketici
garantisi verir. Kilit bırakılmadığında sistem ya LLM çağrısı yapamaz ya da
`visual` simülasyon başlatamaz.

| Sim profili | Kamera | GPU | vLLM |
|---|---|---|---|
| `fast` (varsayılan) | yok | CPU-only render | çalışır |
| `lidar` | yok | CPU | çalışır |
| `visual` | var | GPU gerekli | **durdurulur** |

## 1. Belirti

- LLM çağrıları `gpu_lock` beklemesinde takılı; `neml_gpu_lock_wait_seconds`
  sürekli artıyor.
- `visual` sim `acquire` zaman aşımına uğruyor (varsayılan 300 s).
- `neml-vllm` konteyneri `exited` durumda kalmış ve yeniden başlamamış.

## 2. Gerçek durumu oku

```bash
nvidia-smi                       # GPU'da kim var?
docker ps -a --filter name=neml-vllm
nemlctl status                   # gpu_lock: sahibi, alınma zamanı
```

Üç olasılık:

| Durum | Anlam |
|---|---|
| GPU boş, kilit dolu | **Yetim kilit** — tüketici çöktü, `release` çağrılmadı |
| GPU'da Gazebo var, kilit Gazebo'da | Normal; `visual` koşu sürüyor, bekle |
| GPU'da vLLM var, kilit Gazebo'da | **Tutarsız** — vLLM durdurulmamış veya erken başlamış |

## 3. Yetim kilidi temizle

Kilit sahibi süreç gerçekten ölmüşse:

1. Sahibi doğrula: kilit kaydındaki `consumer` ve zaman damgası.
2. Süreç yaşıyor mu kontrol et (`docker ps`, `ps aux | grep gz`).
3. Yaşamıyorsa kilidi bırak:

```bash
nemlctl gpu unlock --consumer <sahip> --reason "orphan lock after crash"
```

Bu işlem `audit_log`'a yazılır. **Kilidi doğrulamadan bırakma** — iki
tüketici aynı anda GPU'ya girerse ikisi de OOM ile ölür.

## 4. vLLM geri gelmediyse

`visual` koşu bitti ama vLLM başlamadıysa:

```bash
docker start neml-vllm
docker logs --tail 50 neml-vllm
curl localhost:8000/v1/models        # ~40 s sonra yanıt vermeli (§4.5)
```

OOM görüyorsan GPU'da hâlâ başka bir tüketici vardır (`nvidia-smi`).
Önce onu temizle. `--gpu-memory-utilization` değerini yükselterek
çözmeye çalışma; 0.88 sürücü ve görüntü için pay bırakır (§4.2).

## 5. Tekrarlıyorsa

| Bulgu | Eylem |
|---|---|
| `visual` koşular sık çöküyor | Dünya/URDF'i `fast` profilde doğrula; sorun render'da mı fizikte mi ayır |
| Kilit sürekli zaman aşımına uğruyor | `visual` koşu süresi 300 s'yi aşıyor olabilir; koşuyu kısalt veya timeout'u ölçüye göre ayarla |
| `visual` gerçekten gerekli mi | Evrimin %95'i `fast` olmalı (§4.5). Değilse kampanya tasarımı yanlıştır |

§19 risk 2'nin tetikte eylemi geçerlidir: simülasyonu tamamen CPU'ya al,
kamera skill'lerini Faz 6'ya ertele.
