<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# safety_watchdog — L0 bağımsız güvenlik watchdog'u (ATmega328P)

**Sürüm:** v1.0.3 (`NEML_SPEC.md` §13.3 `electronics.safety_mcu.firmware`)
**Kaynak kontrat:** `NEML_SPEC.md` §5.1 (L0), §16 T-071 · Operatör kopyası: `SAFETY.md`

Bu, deponun **en kritik** kodudur. Hiçbir şeye bağlı değildir: ağ yok,
bootloader yok, beyin bağlantısı yok, dinamik bellek yok, Arduino çatısı yok.
Tek işi vardır: ana kontrolcüden (`stm32_motion`) gelen kalp atışını saymak ve
**150 ms** boyunca atış gelmezse motor rölesini açmak.

---

## 1. Arıza-güvenli (fail-safe) kablolama — tasarımın tamamı budur

**Röle, hareketi İZİN VERMEK için enerjilendirilir.**

```
bobin enerjili  (PB0 = HIGH) -> NO kontağı kapalı -> motor barası enerjili
bobin enerjisiz (PB0 = LOW)  -> kontak açık       -> motor barası ölü
```

Böylece ters gidebilecek her şey, **hiçbir şey yapmayarak** robotu durdurur:

| Olay | Sonuç |
|---|---|
| MCU'nun gücü kesildi / reset'te tutuluyor / MCU öldü | PB0 yüksek empedans, 10k pull-down FET'i kapatır → bara ölü |
| Firmware kilitlendi | Donanım watchdog'u (30 ms) reset atar → PB0 yüksek empedans → bara ölü. Dönüşte `WDRF` arızayı **mandallar**, yani kilitlenen kontrolcü yeniden başlayarak robotu enerjilendiremez |
| 150 ms kalp atışı yok | 1 kHz tick PB0'ı düşürür → bara ölü |
| Kalp atışı kablosu koptu | Harici pull-down girişi düşük tutar, kenar gelmez → 150 ms zaman aşımı → bara ölü |
| E-stop'a basıldı | NC mantar buton bobin besleme hattında seri; röle firmware devreye girmeden düşer (§5.1) |
| Watchdog kartının gücü gitti | Bobin enerjisiz → bara ölü |

Röle mantığını ters çevirmek (**"durdurmak için enerjilendir"**) yukarıdaki her
satırı bozar. Bu bir tercih değil, tasarımın kendisidir — değiştirmeyin.

---

## 2. Pin bağlantıları

| Pin | Yön | İşlev |
|---|---|---|
| `PD2 / INT0` | giriş | `stm32_motion` PA5'ten kalp atışı. **10k pull-down GND'ye** + pinde **1k + 10nF RC** parazit filtresi |
| `PB0` | çıkış | Röle FET kapısı, kapıda **10k pull-down GND'ye**. HIGH = harekete izin |
| `PB1` | çıkış | Pi 5'e durum (T-074 `neml_safety` watchdog izleyicisi). HIGH = armed |
| `GND` | — | STM32 ile **ortak toprak zorunlu**, aksi halde kenarlar okunmaz |

Kristal 16 MHz, besleme 5 V. Sigortalar (`make fuses`): `lfuse=0xFF`,
`hfuse=0xD9`, `efuse=0xFC` (brown-out 4.3 V).

**RC filtre neden zorunlu:** Firmware, 20 ms'den yakın gelen kenarı "bu kalp
atışı olamaz" sayıp arıza olarak mandallar. Gerçek kenarlardaki çınlama bu
pencereye düşerse boşuna trip olur. RC filtre bunu donanımda keser.

---

## 3. Durum makinesi

```
DISARMED  (açılış)  --- ardışık 3 geçerli kalp atışı --->  ARMED
ARMED     --- 150 ms sessizlik / çok erken kenar --->      TRIPPED  (mandallı)
TRIPPED   --- yalnızca reset veya güç çevrimi --->         DISARMED
```

- Açılışta röle **daima açıktır**. Enerjilendirmenin tek yolu üç geçerli atıştır.
- Trip **mandallıdır**: kalp atışı geri gelse bile röle kendiliğinden kapanmaz.
  Robotun kendi kendine yeniden enerjilenmesi kabul edilemez. Yeniden devreye
  almak = watchdog kartındaki reset butonu veya güç çevrimi.
- Watchdog reset'i (firmware kilitlenmesi) doğrudan `TRIPPED` durumunda açılır.

Karar mantığı `include/watchdog_core.h` içindedir ve donanımdan tamamen
bağımsızdır; `make test` ile host üzerinde aynen koşar.

---

## 4. Derleme

Ubuntu 24.04:

```bash
sudo apt install gcc-avr avr-libc avrdude
cd firmware/safety_watchdog
make          # build/safety_watchdog.hex + boyut raporu
make test     # host testi: durum makinesi iddiaları
make clean
```

`make test` hiçbir donanım istemez ve CI'da koşar (§18.2). Zamanlamayı kanıtlamaz
— onu `docs/T-071_test_plani.md` kanıtlar.

---

## 5. Flash — **YALNIZCA İNSAN**

> `NEML_SPEC.md` §5.4 `global_forbidden` listesinde **`firmware.flash`** vardır.
> Hiçbir agent, hiçbir otonomi döngüsü, hiçbir MCP sunucusu bu adımı çalıştıramaz.
> Flash bir **insan eylemidir**, elle, CLI ile yapılır. Ayrıca §5.2 Seviye 4
> (MANUFACTURE) onayı gerektirir ve bu onayı **yalnızca `owner`** verebilir.

```bash
# 1. Motor barasını fiziksel olarak ayır. Bataryayı çıkar.
# 2. Sigortalar bir kez (yeni kart):
make fuses
# 3. Flash:
make flash                       # gerekirse: make flash PROGRAMMER=avrispmkII
# 4. T-071 testini tekrar koş ve safety_checks tablosuna yaz.
```

Flash'tan sonra `docs/T-071_test_plani.md` **yeniden koşulmadan** robot
enerjilendirilmez. Yeni bir firmware sürümü, eski doğrulama kaydını geçersiz kılar.

---

## 6. Doğrulama

| Ne | Nasıl | Ne zaman |
|---|---|---|
| Durum makinesi | `make test` | Her commit (CI) |
| 150 ms trip zamanı | `docs/T-071_test_plani.md` — osiloskop | Her firmware değişikliğinde, T-071 kabulünde |
| Oturum öncesi hızlı test | `SAFETY.md` §0 | **Her fiziksel oturumdan önce**, `safety_checks` kaydı ile |

Kayıt yoksa `neml-brain` fiziksel görev başlatmayı reddeder (§5.1, kodla zorlanır).
