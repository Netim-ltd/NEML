<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-008 — Kopyaleft araçların süreç sınırında izolasyonu

**Durum:** Kabul edildi · **Tarih:** 2026-09-15 · **Kaynak:** NEML_SPEC.md §1.1, §1.3

> Bu ADR hukuki tavsiye değildir. Ticarileştirme öncesi bir fikri mülkiyet
> avukatına danışılmalıdır (§1.3).

## Bağlam

NEML'in ürettiği **her** çıktının mülkiyeti tek kişiye aittir (§1.1). Buna
karşılık boru hattındaki bazı araçlar kopyaleft lisanslıdır:

| Araç | Lisans | Çıktıya etkisi |
|---|---|---|
| FreeCAD | LGPL-2.1+ | Yok — araç olarak kullanım çıktıyı etkilemez |
| KiCad | GPL-3.0 | Yok — araçla üretilen tasarım sizindir |
| PrusaSlicer | AGPL-3.0 | **Dikkat** — ağ servisine gömülürse kaynak açma yükümlülüğü doğar |

Kritik fark, aracı **kullanmak** ile kodunu **türetmek** arasındadır.
Özellikle AGPL, ağ üzerinden erişilen bir servise gömülmüş kodu da kapsar;
NEML ise tam olarak ağ servislerinden oluşan bir sistemdir.

## Karar

Kopyaleft lisanslı hiçbir kod NEML kaynak ağacına **kopyalanmaz**. Bu araçlar
yalnızca **ayrı süreç** olarak çağrılır: CLI alt süreci ya da ayrı bir MCP
sunucusu. Süreç sınırı, izolasyon sınırıdır.

Örnekler:

- PrusaSlicer: `prusa-slicer --export-gcode ...` alt süreç çağrısı (§6.4).
  Kütüphane olarak bağlanması yasaktır.
- KiCad: `kicad-cli` ve harici Python API; proje dosyaları üretilir, KiCad
  kodu taşınmaz.
- FreeCAD: headless çağrı, parametrik şablonlar bizim kodumuzdur (§12.1).
- `mcp_servers/vendor/` altında yalnızca **konfigürasyon** bulunur, kod değil
  (§15).

## Gerekçe

Bu, §1.1'deki münhasır mülkiyeti korumanın **teknik şartıdır**. Bir kütüphane
çağrısı ile bir alt süreç çağrısı işlevsel olarak benzer görünür ama lisans
açısından farklı dünyalardır. Sınırı kodda tutmak, sonradan denetlemekten
ucuzdur.

## Sonuçlar

- CI'da bloklayıcı bir **lisans taraması** vardır (§18.2 kapı 8) ve aynı
  kontrol `pre-commit`'te yereldir: kaynak ağacında kopyaleft lisans başlığı
  bulunursa commit reddedilir.
- Alt süreç çağrısı performans maliyeti getirir (süreç başlatma, dosya
  üzerinden veri alışverişi). Bu maliyet kabul edilmiştir.
- Yeni bir araç eklenirken **önce lisansı** kontrol edilir. Kopyaleft ise
  yalnızca süreç sınırının dışında kullanılabilir.
- Qwen2.5 model lisansı aile içinde değişir; **indirmeden önce doğrulanır**
  (§1.3).
