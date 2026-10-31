<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Runbook: fiziksel kabul adımları (T-070 … T-083)

Bu adımlar donanım ister; yazılım yalnızca **kaydı** tutar. Sıra atlanmaz, SAFETY.md
okunmadan başlanmaz.

## T-070 Montaj ve kütle

1. `nemlctl` ile aktif genom: `quadruped_v2`. BOM'u genomdan al (`hardware/electronics/bom`).
2. Robotu monte et, **tartı**. Ölçülen kütle CAD kütlesinin ±%10'u içinde olmalı.
3. Kaydı kalite formundan gir (mobil → Üretim → kalite kontrol); genome `body_mass_kg` güncellenir.
4. Fark %10'u aşarsa görev reddedilir: CAD yoğunluğu ya da eksik parça araştırılır.

## T-071 / T-075 E-stop ve watchdog kabulü

1. Robotu enerjilendir (motorlar yüksüz, tezgâhta).
2. **E-stop:** mantar butona bas → motor gücü kesilmeli; tezgâh butonuyla tekrarla.
3. **Watchdog:** heartbeat'i kes → osiloskopla **röle ≤ 150 ms** içinde açıldığını doğrula
   (`firmware/safety_watchdog/docs/T-071_test_plani.md`).
4. **Akım limiti:** test yükünde donanım karşılaştırıcısının açtığını doğrula.
5. Video çek, arşivle. Sonra kaydı gir:

   ```bash
   nemlctl robot safety-check R01 --estop --watchdog --current-limit
   ```

   Kayıt yoksa ya da 12 saatten eskiyse beyin fiziksel görevi kodla reddeder.

## T-077 Reality gap ve fizik kalibrasyonu

1. Beş referans manevrayı gerçek robotta koş (`scripts/calibration/calibrate.py run`); her biri
   onay bekler.
2. `calibrate.py gap` ile boşluğu hesapla. **≤ 0.20** olmalı.
3. Üstündeyse `calibrate.py fit`: `physics` parametreleri (`POST /v1/sim/run`) uydurulur ve
   robota yeni değerler yazılır. Gap ≤ 0.20 olana kadar evrim durur.

## T-080 … T-083 Çoklu robot

1. İkinci/üçüncü robotu kaydet; her biri için **ayrı** `safety-check`.
2. Üçü de `idle` iken Zenoh ile 30 dk kesintisiz çalıştır; paket kaybı < %1.
3. Bir robotu kapat: görevi diğerlerine devredilmeli.
4. Bağlantıyı kes: robot 2 s içinde güvenli duruma geçmeli.

## Bitince

Her adımın tarihini, kimin yaptığını ve eki (video, ölçüm tablosu) `docs/` altında ilgili
oturum notuna yaz. Yazılım tarafında karşılığı: `safety_checks` satırı, kalite formu, kalibrasyon
çıktısı.
