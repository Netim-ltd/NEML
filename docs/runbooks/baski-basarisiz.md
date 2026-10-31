<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Runbook — Baskı başarısız / parça kalite kontrolünden geçmedi

**Kaynak:** NEML_SPEC.md §12.5, §12.3, §14.4 · **Önem:** Orta

## 0. Baskı hâlâ sürüyorsa

Duman, koku, çarpma sesi veya nozzle'ın parçaya vurması varsa:
**akıllı prizden gücü kes.** Thermal runaway koruması son savunmadır,
ilk savunma sensin (§5.1). Sonra bu runbook'a dön.

## 1. Kalite kontrol eşikleri (§12.5)

Sonuç mobil uygulamada forma girilir:

| Kontrol | Yöntem | Eşik |
|---|---|---|
| Kritik boyutlar (3 nokta) | Kumpas | ±0.3 mm |
| Delik çapı | Pin gauge | Geçer/geçmez |
| Kütle | Terazi | CAD tahmininin ±%5'i |
| Katman yapışması | Görsel + elle bük | Ret/kabul |
| Warp | Düz yüzey + ışık | ≤ 0.5 mm |

## 2. Başarısızlık tipini ayır

| Belirti | Kök neden sınıfı | İlk bakılacak |
|---|---|---|
| Baskı yarıda durdu | Yazıcı/host | PrusaLink durumu, filament bitti mi, tıkanma |
| Warp / ilk katman kalkması | Proses | Tabla sıcaklığı, yapışma, hazne sıcaklığı |
| Katmanlar ayrılıyor | Malzeme | PA6-CF nemlenmiş olabilir (§19 risk 8) |
| Boyut sistematik sapma | Kalibrasyon | Slicer kompanzasyonu, ekstrüzyon çarpanı |
| Kütle CAD'den çok farklı | Tasarım/slicer | Infill, duvar sayısı, destek hacmi |
| Geometri zaten üretilemez | **Tasarım** | DFM doğrulayıcı bunu neden geçirdi? (§12.3) |

## 3. Kaydet — bu bir öğrenme girdisidir

1. Sonucu mobil formdan gir; parça `manufacturing/jobs/` kaydına bağlanır.
2. Başarısızlık `failure_tag` profili ile etiketlenir, chunk'lanıp gömülür
   ve `memory_chunks`'a yazılır (§14.6).
3. Fotoğraf ekle. Görsel kanıt olmadan warp/katman tartışması yürümez.

## 4. Sistematik sapma varsa

**3 ardışık parçada aynı yönde sapma** varsa bu tek seferlik değildir:
slicer kompanzasyonu **otomatik güncellenir** ve `audit_log`'a yazılır
(§12.5). Otomatik güncelleme tetiklenmediyse sayacı kontrol et; elle
kompanzasyon girmeden önce üç ölçümün gerçekten aynı yönde olduğunu doğrula.

## 5. DFM kaçağıysa

Parça fiziksel olarak üretilemezdi ve DFM doğrulayıcı (§12.3) geçirdiyse
**asıl hata doğrulayıcıdadır**, baskıda değil:

1. Başarısız parametre setini yaz.
2. DFM doğrulayıcıya bu seti **regresyon testi** olarak ekle.
3. Kuralı düzelt, test yeşile dönsün.
4. Aynı şablonla üretilmiş bekleyen baskıları kuyruktan çıkar.

Kural eklemeden yeni baskı onaylama; aynı hatayı filament harcayarak
tekrar öğrenirsin.

## 6. Bütçe etkisi

Başarısız baskı filament bütçesinden düşer (500 g/gün, §14.4). Limit
dolduğunda baskı onayı reddedilir — bu doğru davranıştır, limiti
yükseltme refleksi verme. Bkz. [`butce-asimi.md`](butce-asimi.md).

## 7. Tekrarlayan malzeme sorunu (§19 risk 8)

PA6-CF tutarsızlığı sürüyorsa: filament kurutucu + kapalı hazne zorunludur.
Düzelmiyorsa tetikte eylem **PETG'ye düşmektir**; malzeme değişikliği
genome'a ve slicer profiline yazılır.
