<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Runbook — Reality gap 0.20'yi aştı

**Kaynak:** NEML_SPEC.md §11.3 · **Önem:** Yüksek

```
gap = mean_over_manevra( |sim_metrik − real_metrik| / real_metrik )
```

| gap | Anlam | Eylem |
|---|---|---|
| ≤ 0.10 | İyi | Normal çalışma |
| 0.10–0.20 | Kabul edilebilir | İzle |
| > 0.20 | Kalibre değil | **Evrim durdurulur**, fizik yeniden kalibre edilir |

Gap > 0.20 iken simülasyon sonuçları gerçeği temsil etmez. Bu durumda
üretilen "iyileşme" ölçüm değil, gürültüdür (§21).

## 1. Evrimi durdur

Bu otomatiktir, ama doğrula:

```bash
nemlctl campaign status        # aktif kampanya 'paused' olmalı
```

Gap kapanana kadar yeni nesil üretilmez, `candidate` kabul edilmez.

## 2. Hangi manevrada koptuğunu bul

Toplam gap'e bakma; **manevra bazında** bak (§11.3):

| Manevra | Sapma büyükse ilk şüpheli |
|---|---|
| `M1_straight` | Yüzey sürtünmesi, motor kazancı |
| `M2_turn` | Sürtünme anizotropisi, eklem damping |
| `M3_step` | Temas modeli, tork limiti, gövde eylemsizliği |
| `M4_stand` | Eklem damping, IMU gürültü modeli, kontrol gecikmesi |
| `M5_payload` | Kütle dağılımı, gövde eylemsizliği düzeltmesi |

Tek manevrada bozukluk → hedefli düzeltme. Hepsinde bozukluk → global bir
parametre (kütle ölçeği, gecikme) kaymıştır.

## 3. Referans veriyi doğrula

Kalibrasyon kötü veriyle yapılırsa durum kötüleşir. Önce:

- 5 manevra × 10 tekrar tam mı? Eksik tekrar varsa tamamla.
- Batarya seviyesi tekrarlar arasında düştü mü? Düşük SoC motor
  performansını değiştirir; tekrarları benzer SoC'de al.
- Fiziksel bir değişiklik oldu mu? Yeni parça, sıkılmış vida, değişen
  yüzey. Değiştiyse **URDF ve kütle özellikleri güncel mi** kontrol et.

## 4. Yeniden kalibre et

Uydurulan parametreler (§11.3):

- sürtünme katsayısı
- eklem damping
- motor kazancı
- gövde eylemsizliği düzeltmesi
- iletişim gecikmesi

`scipy.optimize.least_squares` ile referans manevra verisine uydurulur.

```bash
python scripts/calibration/fit_physics.py --maneuvers M1,M2,M3,M4,M5
```

## 5. Doğrula

1. Kalibrasyon sonrası referans setini **yeniden koş** (sim tarafı).
2. Gap'i yeniden hesapla. ≤ 0.10 hedeftir, 0.10–0.20 izlemeye alınır.
3. Determinizm testini koş: aynı seed 10 koşu, metrik sapması ≤ %2
   (§11.2). Sapma aşılırsa koşular `deterministic=false` işaretlenir ve
   evrim kararında kullanılmaz.
4. Kalibrasyon parametrelerini ve tarihini kaydet.

## 6. Gap kapanmıyorsa (§19 risk 3)

Fizik modelinin ulaşamadığı bir fark vardır (esneme, backlash, kablo
sürtünmesi). Tetikte eylem: **yalnızca yazılım evrimi yap, donanım evrimini
durdur.** Donanım değişiklikleri elle tasarlanıp elle doğrulanır.
