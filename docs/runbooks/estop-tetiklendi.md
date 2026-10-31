<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Runbook — E-stop tetiklendi

**Kaynak:** NEML_SPEC.md §5.1, §5.2 · **Önem:** Kritik

E-stop'a basıldı ya da watchdog motor rölesini açtı. Motor gücü kesiktir.

## 1. Hemen (ilk 60 saniye)

1. **Robota yaklaşma.** Motor gücü kesik olsa bile kapasitör boşalması ve
   yay/yerçekimi kaynaklı hareket olabilir.
2. Batarya ana anahtarını kapat.
3. Alanı boşalt; başka kimse varsa uzaklaştır.
4. Yazıcı da çalışıyorsa akıllı prizden gücünü kes.

## 2. Sınıflandır — neden tetiklendi?

| Belirti | Olası neden |
|---|---|
| İnsan bastı | Beklenmedik hareket, yanlış seviye, önlem |
| Watchdog kesti (butona basılmadı) | Ana kontrolcü heartbeat'i kesti: STM32 çöktü, USB/seri koptu, Pi5 yüklendi veya yeniden başladı |
| Akım limiti kesti | Sıkışma, kısa devre, aşırı yük, mekanik kilitlenme |
| Kendiliğinden, sebepsiz | E-stop kablosunda kopukluk (NC devre açıldı) — bu **doğru** davranıştır |

## 3. Kanıt topla (temizlemeden önce)

```bash
nemlctl status
journalctl -u neml-brain --since "-15 min" > /tmp/estop_brain.log
# rosbag2 kaydı otomatik tutulur; başarısızlık kayıtları kalıcıdır (§18.3)
```

- `audit_log`'dan son araç çağrılarını ve onay referansını çıkar.
- Son komut hangi dağıtım seviyesindeydi? Onayı kimde, ne zaman alındı?
- Robot üzerinde gözle hasar kontrolü: eklem, kablo, konnektör, çerçeve.

## 4. Kök nedeni bulmadan yeniden enerjilendirme

Bu satır pazarlığa açık değildir. Sebep bilinmeden güç verilmez.

| Kök neden | Yapılacak |
|---|---|
| Heartbeat kesintisi | STM32 firmware ve seri bağlantıyı kontrol et; Pi5 yük/sıcaklık geçmişine bak |
| Akım limiti | Mekanik sıkışmayı gider, kablajı ölç; tork limitini **yükseltme** (derleme zamanı sabiti, §5.1) |
| E-stop kablosu | Kabloyu onar; NC mantığını koru, NO butona çevirme |
| Yazılım kaynaklı hatalı komut | Görevi iptal et, ilgili skill'i `validated` durumundan düşür, regresyon testi ekle |

## 5. Yeniden başlatma

1. Donanımı onar/doğrula.
2. **SAFETY.md §0 testlerini baştan yap** — e-stop + watchdog — ve
   `safety_checks`'e yaz. Eski kayıt geçersizdir.
3. Bir seviye **aşağıdan** başla: olay Seviye 3'te olduysa Seviye 1'den
   devam et.
4. Olayı `audit_log`'a olay kaydı olarak yaz.

## 6. Donanıma zarar verildiyse (§19 risk 5)

- Sistemi tamamen durdur (`nemlctl` ile otonom döngüyü duraklat).
- Olay incelemesi yap: ne oldu, hangi kapı çalışmadı, neden fark edilmedi.
- **`SAFETY.md` güncellenmeden sistem yeniden çalıştırılmaz.**
