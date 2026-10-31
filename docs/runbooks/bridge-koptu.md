<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Runbook — Cloud bridge koptu

**Kaynak:** NEML_SPEC.md §3.1, §9.5 · **Önem:** Orta

Lab ile uzak sunucu arasındaki kalıcı WSS bağlantısı kesildi.
Mobil/web `BrainStatus{online:false}` görüyor.

**Önce şunu bil: lab çevrimdışıyken de tam çalışır (§3.1).** Otonom döngü,
simülasyon, evrim ve yerel görevler devam eder. Kaybedilen tek şey uzaktan
görünürlük ve uzaktan komuttur. Panik yok.

## 1. Kopmayı doğrula

```bash
nemlctl status                          # bridge: connected/disconnected
journalctl -u neml-brain -f | grep bridge
```

Prometheus: `neml_bridge_connected` = 0.

Heartbeat 15 s'dir; 45 s yanıtsızlık kopuk sayılır (§9.5). Kısa
dalgalanmalar normaldir — bridge 1s → 2s → 4s … max 60 s üstel geri
çekilme ile kendi kendine bağlanır. **İlk 2 dakika müdahale etme.**

## 2. Katmanı bul

| Kontrol | Komut | Sonuç kopuksa |
|---|---|---|
| Lab internet çıkışı | `curl -sS https://api.neml.example.com/health` | Ev/ofis internetine bak, modem/ISP |
| DNS | `getent hosts api.neml.example.com` | DNS sorunu, resolver'ı kontrol et |
| TLS / sertifika | `openssl s_client -connect api.neml.example.com:443` | Sertifika süresi dolmuş olabilir |
| Uzak servis | Sunucuda `systemctl status neml-api` | .NET API düşmüş, yeniden başlat |
| Kimlik | `NEML_API_KEY` ve IP kısıtı | Anahtar döndürülmüş ya da IP değişmiş (§5.5) |

**Sık neden:** ev IP'si değişti ve sunucudaki IP kısıtı eski adresi
tutuyor. Sunucu tarafında `X-NEML-Node` başlığıyla gelen reddedilmiş
istekleri ara.

## 3. Kuyruğu koru

Çevrimdışıyken telemetri SQLite kuyruğuna yazılır
(`/var/lib/neml/outbox.db`, max 500 MB, FIFO). Dolunca **en eski telemetri**
düşer; `event` ve `command_ack` asla düşmez (§9.5).

```bash
ls -lh /var/lib/neml/outbox.db          # boyut 500 MB'a yaklaşıyor mu?
```

Kopma uzarsa telemetri kaybı olur ama olay ve onay akışı korunur. Kuyruk
dosyasını **silme**; silersen geri gönderilecek kanıtı silmiş olursun.

## 4. Bağlantı geri geldiğinde

- Kuyruk sıralı olarak boşalır. Sunucu, `idempotency_key` sayesinde
  tekrarlanan mesajları sessizce yok sayar; çift işlem olmaz (§3.1).
- `seq` monoton artan olmalıdır. Loglarda `seq` atlaması varsa kuyruk
  düşürmesi olmuştur — beklenen olabilir, ama kaydet.
- Bekleyen onay isteklerini kontrol et: kopma 24 saati aştıysa istekler
  zaman aşımından reddedilmiş olabilir (§5.2). Gerekliyse yeniden iste.

## 5. Güvenlik ihlali şüphesi varsa (§19 risk 11)

Bridge beklenmedik şekilde reddediliyor, sunucuda tanımadığın oturumlar
varsa: **anahtarları döndür ve bridge'i kapalı tut.** Lab çevrimdışı
çalışmaya devam eder; bu, kapatmanın maliyetini düşük tutar.
