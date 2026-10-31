<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# T-071 — Watchdog kabul testi (osiloskop ile)

**Kabul kriteri (`NEML_SPEC.md` §16):** *"150 ms heartbeat kaybında röle açılıyor —
osiloskopla doğrulandı."*

Bu belge o doğrulamanın nasıl yapılacağını tanımlar. Testi **bir insan** koşar.
Sonuç `safety_checks` tablosuna ve ekran görüntüleri/video arşive girer (T-075).

---

## 0. Ön koşullar

- [ ] `make test` geçti (durum makinesi host testi).
- [ ] `build/safety_watchdog.hex` karta yazıldı (`make flash`, §5.2 Seviye 4 onayı ile).
- [ ] **Motor barası fiziksel olarak ayrıldı.** Bu testte motor dönmez. Röle
      kontağı boşta ya da kukla yük (12 V lamba) ile yüklenir.
- [ ] Batarya çıkarıldı; watchdog kartı ve STM32 tezgâh beslemesinden çalışıyor.
- [ ] STM32 ile watchdog kartı arasında **ortak toprak** var.

## 1. Gerekli ekipman

| Ekipman | Gereksinim |
|---|---|
| Osiloskop | ≥ 2 kanal, tek atım (single shot) yakalama, ≥ 1 MSa/s, ekran görüntüsü alabilen |
| Prob ×2 | 10:1, kısa toprak yayı |
| Ayrı toprak referansı | Her iki prob da watchdog kartının GND'sine bağlanır |
| Kukla yük (opsiyonel) | 12 V / 5 W lamba — kontağın gerçekten açıldığını gözle görmek için |
| Kronometre | Adım 6 soak testi |

## 2. Prob yerleşimi

| Kanal | Nokta | Beklenen |
|---|---|---|
| CH1 | `PD2` (kalp atışı girişi, RC filtrenin **MCU tarafı**) | 50 ms'de bir kenar değiştiren kare dalga |
| CH2 | `PB0` (röle FET kapı sürüşü) | Armed iken sabit HIGH |
| CH2 (alternatif) | Röle kontağının yük tarafı | Kontağın gerçekten açıldığını ölçmek için — bu ölçümde mekanik düşme süresi de dahil olur |

Zaman tabanı: **20 ms/böl** (toplam 200 ms pencere). Tetik: **CH2 düşen kenar**,
mod **Single**.

---

## 3. Adım 1 — Kalp atışı periyodunun doğrulanması

STM32 çalışırken CH1'i ölç.

- **Beklenen:** kenarlar arası 50 ms ± %5 (47.5–52.5 ms).
- **Neden önemli:** Firmware 150 ms zaman aşımını uygular; ana kontrolcü 149 ms
  periyotla atarsa test geçer ama marj kalmaz. Periyot kayması `stm32_motion`
  tarafında aranır.
- **Kayıt:** ölçülen periyot, tepe-tepe genlik, yükselme süresi.

**Ret:** periyot 50 ms ± %5 dışındaysa test durur, `stm32_motion` incelenir.

## 4. Adım 2 — Kol alma (arming) davranışı

1. Watchdog kartına reset at (STM32 kalp atarken).
2. CH2'yi izle.

- **Beklenen:** PB0 reset anında LOW; **3 kalp atışından sonra** (≈ 100–150 ms)
  HIGH'a geçer. Önce değil.
- **Neden:** açılışta röle daima açık olmalı (§5.1 fail-safe).

## 5. Adım 3 — **Ana ölçüm: 150 ms zaman aşımı**

1. Sistem `ARMED` (CH2 HIGH, lamba yanıyor).
2. Osiloskobu Single / CH2 düşen kenar ile kur.
3. STM32'nin kalp atışını kes. Kesme yöntemi (biri):
   - STM32'yi reset'te tut (tercih edilen — gerçek arıza senaryosu), **veya**
   - kalp atışı kablosunu sök (kablo kopması senaryosu).
4. Yakalanan dalgada **CH1'in son kenarı** ile **CH2'nin düşen kenarı** arasını
   imleçle ölç.

**Kabul:**

| Ölçüm | Bütçe |
|---|---|
| Son kalp atışı kenarı → `PB0` düşüşü | **150 ms +1 / −2 ms** (firmware tick jitter'ı ±1 ms) |
| `PB0` düşüşü → röle kontağının açılması | ≤ 15 ms (röle veri sayfası bırakma süresi) |
| Son kalp atışı → motor barası ölü (toplam) | **≤ 165 ms** |

> §5.1 ve T-071'deki 150 ms, **firmware'in kararıdır** ve `PB0`'da ölçülür.
> Rölenin mekanik bırakma süresi bunun üstüne biner; kullanılan röle 15 ms'den
> yavaş bırakıyorsa röle değişir.

**Tekrar sayısı: 10.** Her tekrardan sonra watchdog kartına reset atılır (trip
mandallıdır — bu kasıtlıdır, §5.1). Her tekrarın ekran görüntüsü alınır.

**Kaydedilecek:** 10 ölçümün min / ortalama / maks değeri. Maks > 151 ms veya
min < 148 ms ise test **başarısızdır**.

## 6. Adım 4 — Donanım watchdog'u (firmware kilitlenmesi)

Bu adım ikinci katmanı doğrular: firmware kilitlenirse ne olur.

```bash
make wdttest
# build/safety_watchdog_WDTTEST.hex --> karta yaz
```

Bu yapı ~2 s sonra kesmeleri kapatıp bilerek kilitlenir.

- **Beklenen:** kilitlenmeden ≤ 30 ms sonra `PB0` düşer (donanım WDT reset'i) ve
  **bir daha yükselmez** — `WDRF` mandalı yüzünden MCU yeniden başlasa bile röle
  kapalı kalır. CH2'de tek bir düşen kenar görülür, periyodik açılıp kapanma
  **görülmemelidir**.
- **Başarısızlık işareti:** PB0'ın tekrar tekrar HIGH/LOW olması → mandal
  çalışmıyor, firmware reddedilir.

> **Testten sonra operasyonel hex mutlaka geri yazılır** (`make flash`) ve
> Adım 3 tekrarlanır. `_WDTTEST` yapısı robot üzerinde bırakılamaz.

## 7. Adım 5 — Ölü MCU / güç kaybı

1. Sistem `ARMED`.
2. Watchdog kartının beslemesini kes.

- **Beklenen:** röle derhal düşer, motor barası ölür. Firmware devrede değildir;
  bu adım kablolamayı doğrular.

Aynı testi MCU'yu reset hattından GND'ye çekerek tekrarla — sonuç aynı olmalı.

## 8. Adım 6 — Yanlış alarm (nuisance trip) soak testi

1. Sistem `ARMED`, STM32 normal çalışıyor, **motorlar dönüyor** (tezgâh, Seviye 1
   BENCH, §5.2 onayı ile — tekerlekler havada).
2. **10 dakika** kesintisiz çalıştır.

- **Beklenen:** hiç trip yok. Bir trip olursa kalp atışı hattında parazit vardır:
  RC filtreyi, toprak dönüş yolunu ve kablo güzergâhını (motor kablolarından ayır)
  kontrol et.
- **Neden gerekli:** 20 ms'den yakın kenar arıza sayılır. Motorlar dönerken
  elektriksel gürültü en yüksektir; test o koşulda yapılmazsa hiçbir şey ispat
  etmez.

---

## 9. Sonuç kaydı

Test tamamlandığında `safety_checks` tablosuna yazılır:

| Alan | İçerik |
|---|---|
| Test | `T-071 watchdog scope verification` |
| Firmware | `firmware/safety_watchdog@v1.0.3` + hex SHA-256 |
| Ölçümler | Adım 3'ün 10 tekrarının min/ort/maks değeri |
| Adım 1,2,4,5,6 | geçti / kaldı |
| Ekler | Osiloskop ekran görüntüleri, Adım 5 videosu (T-075) |
| Operatör | Kim, ne zaman |

**Herhangi bir adım kalırsa fiziksel çalışma başlamaz.** `SAFETY.md` §3'teki
"Watchdog 150 ms'de kesmiyor" satırı uygulanır.
