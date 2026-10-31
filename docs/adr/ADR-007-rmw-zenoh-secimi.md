<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-007 — Middleware RMW olarak `rmw_zenoh_cpp`

**Durum:** Kabul edildi · **Tarih:** 2026-09-15 · **Kaynak:** NEML_SPEC.md §2, §17.2

## Bağlam

ROS 2 Jazzy varsayılan olarak DDS tabanlı bir RMW ile gelir (Fast DDS,
Cyclone DDS). NEML'de robotlar lab istasyonuna **WiFi 5 GHz** üzerinden
bağlanır ve sayıları zamanla artar (swarm, Faz 5). DDS'in çoklu yayın
(multicast) tabanlı keşfi, WiFi'de kötü ölçeklenir: her düğüm her düğümü
keşfetmeye çalışır, keşif trafiği düğüm sayısının karesiyle büyür ve
kablosuz ortamda paket kaybı bunu daha da kötüleştirir.

## Karar

`RMW_IMPLEMENTATION=rmw_zenoh_cpp` kullanılır. `ROS_DOMAIN_ID=42`,
router konfigürasyonu `/srv/neml/config/zenoh_router.json5`. Zenoh router
LAN'da `:7447` portundadır (§17.1).

## Gerekçe

- Zenoh, router üzerinden **aracılı** (brokered) keşif yapar; kablosuz ağda
  multicast fırtınası oluşmaz.
- Yönlendirilebilir mimarisi, ileride robotların farklı alt ağlara veya
  WAN'a çıkması gerektiğinde köprü gerektirmez.
- ROS 2 Jazzy'de resmi olarak desteklenen bir RMW'dir; uygulama kodu RMW
  bilmez, yalnızca ortam değişkeni değişir.

## Sonuçlar

- Zenoh router bir **bağımlılıktır**: düşerse keşif durur. Router lab
  istasyonunda servis olarak çalışır ve izlenir.
- QoS profilleri topic sınıfına göre uygulanır (§17.2) ve
  `config/gz_bridge.yaml` içinde açıkça yazılıdır:

  | Topic sınıfı | Reliability | Durability | History |
  |---|---|---|---|
  | `/*/telemetry/*` | BEST_EFFORT | VOLATILE | KEEP_LAST(1) |
  | `/*/cmd/*` | RELIABLE | VOLATILE | KEEP_LAST(10) |
  | `/*/state` | RELIABLE | TRANSIENT_LOCAL | KEEP_LAST(1) |
  | `/*/camera/*` | BEST_EFFORT | VOLATILE | KEEP_LAST(1) |

- **Kamera akışı ham olarak swarm ağına verilmez.** Robot üzerinde JPEG
  sıkıştırılır ve yalnızca talep üzerine gönderilir (§17.2).
- §19 risk 7 gerçekleşirse (WiFi'de swarm gecikmesi): 5 GHz'de ayrı SSID,
  kamera akışını kes.
