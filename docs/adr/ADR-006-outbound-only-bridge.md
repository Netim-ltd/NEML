<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-006 — NAT arkasındaki lab için outbound-only WSS bridge

**Durum:** Kabul edildi · **Tarih:** 2026-09-15 · **Kaynak:** NEML_SPEC.md §3.1, §9.5

## Bağlam

Laboratuvar istasyonu ev/ofis ağındadır ve NAT arkasındadır; dışarıdan
erişilemez. Mobil ve web istemcileri ise internet üzerindeki .NET API'ye
bağlanır. Klasik çözümler: port yönlendirme, VPN (WireGuard/Tailscale),
ters tünel (ngrok vb.) ya da giden yönde kalıcı bağlantı.

## Karar

**Uzak sunucu asla laba bağlanmaz.** Lab istasyonundaki `cloud-bridge`,
uzak API'ye **giden yönde** kalıcı bir WebSocket (WSS) açar ve açık tutar.
Mobil/web komutları sunucudaki **komut kuyruğuna** yazılır; bridge bunları
çeker, uygular ve sonucu geri yollar.

## Gerekçe

- Port yönlendirme, ev ağında bir robot laboratuvarını internete açmak
  demektir. Saldırı yüzeyi kabul edilemez (§19 risk 11).
- Giden bağlantı NAT'ta değişiklik gerektirmez, taşınabilir ağlarda
  (misafir WiFi, mobil hotspot) da çalışır.
- Kuyruk modeli, sunucunun robotu **doğrudan kontrol edemediği** anlamına
  gelir; sunucu yalnızca kuyruğa yazar. Sunucu ele geçirilse bile donanıma
  giden yol §5.2 onay kapılarından geçmek zorundadır.
- Lab **çevrimdışıyken de tam çalışır**. Otonom döngü buluta bağımlı
  değildir; bu, sistemin temel özelliğidir.

## Sonuçlar

- Yeniden bağlanma üstel geri çekilmelidir: 1s → 2s → 4s … max 60 s (§3.1).
- Telemetri çevrimdışıyken yerel kalıcı kuyruğa yazılır (SQLite,
  `/var/lib/neml/outbox.db`, max 500 MB, FIFO). Dolunca **en eski telemetri**
  düşürülür; `event` ve `command_ack` asla düşmez (§9.5).
- Her mesajda `seq` (monoton artan) ve `idempotency_key` vardır; tekrarlanan
  mesajlar sunucuda sessizce yok sayılır. Bu, yeniden bağlanmada çift işlemi
  engeller.
- Heartbeat 15 s; 45 s yanıtsızlık bağlantıyı kopuk sayar ve
  `BrainStatus{online:false}` yayınlanır (§9.5).
- Sunucudan laba anlık "push" yoktur; gecikme kuyruk çevrim süresi kadardır.
  Bu, kabul edilen bir takastır.
