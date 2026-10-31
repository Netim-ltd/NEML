<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-004 — 3 GB VRAM kısıtı mimariyi belirler

**Durum:** Kabul edildi · **Tarih:** 2026-09-15 · **Kaynak:** NEML_SPEC.md §4.1, §4.2, §4.5, §4.6

## Bağlam

Laboratuvar istasyonunda kullanılabilir GPU belleği **3 GB**'dır. Bu bellekte
çalışabilecek model sınıfı ~1.5B parametre, 4-bit kuantizedir. Böyle bir
model şunları **yapamaz** (§4.1):

- Sıfırdan doğru FreeCAD Python scripti yazmak
- Şematik topolojisi tasarlamak
- Uzun bağlamlı mimari kararlar almak
- Güvenilir serbest-biçimli araç seçimi yapmak

## Karar

3 GB, giderilmesi gereken bir eksiklik değil, mimarinin **girdisidir**.
Tasarım, modelin yapabildiği işi yapmasına ve yapamadığı işi hiç
denememesine göre kurulur. Somut sonuçları:

1. Tek model, altı prompt profili (§4.4) — ikinci model yüklenmez.
2. Kısıtlı üretim mimarisi zorunludur (§4.3, ADR-005).
3. GPU tek tüketicilidir: `GpuLock` ile vLLM ve Gazebo asla aynı anda
   GPU'da olmaz (§4.5).
4. Varsayılan sim profili `fast`'tir; render CPU'dadır.
5. Gömme modeli CPU'da, ONNX Runtime int8 ile çalışır (§4.6).
6. vLLM bayrakları belleği hedefler: `--enforce-eager` (CUDA graph
   belleğinden ~300-500 MB tasarruf), `--max-model-len 4096`,
   `--max-num-seqs 2`, `--gpu-memory-utilization 0.88`.

## Gerekçe

Donanımı yok sayıp "model daha iyisini yapar" varsayan bir tasarım, ilk
gerçek koşuda OOM ile durur. Kısıtı mimariye gömmek, sistemi küçük modelle
**doğru** çalışır hale getirir; büyük model gelirse sistem yalnızca hızlanır,
yeniden yazılmaz.

## Sonuçlar

- `visual` profili pahalıdır (~40 s vLLM yeniden başlatma) ve planlanarak
  kullanılır; evrimin %95'i `fast`'tedir.
- GPU süresi günlük bütçeye tabidir: 6 saat (§14.4).
- Daha da kısıtlı donanımda yedek yol `Qwen2.5-0.5B-Instruct`'tır; o model
  yalnızca sınıflandırma yapar, `param_fill` adımı elle doldurulur (§4.2).
- Bu ADR, §19 risk 2'nin ("3 GB GPU yetersiz") azaltmasıdır. Tetikte eylem:
  simülasyonu tamamen CPU'ya al, kamera skill'lerini Faz 6'ya ertele.
