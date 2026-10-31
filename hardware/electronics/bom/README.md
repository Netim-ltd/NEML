<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# BOM çıktı klasörü (NEML_SPEC.md §13.2)

`§13.2` doğrulama zincirinin BOM adımı dosyalarını buraya yazar:

```
<template_id>-<input_hash[:12]>.csv
```

`input_hash`, şablon kaynağının ve parametrelerin SHA-256'sıdır (§0.6). Aynı
tasarım her zaman aynı dosya adını üretir; şablon değişirse ad da değişir.

## Sütunlar

Başlık satırı **doğrudan §7 `bom_items` tablosunun kolon kümesidir** (otomatik
üretilen `id` hariç), böylece yükleyici basit bir `COPY` çağrısıdır:

```sql
COPY bom_items (genome_id, ref, part_number, qty, unit_cost_try, supplier, lead_time_days)
FROM 'hardware/electronics/bom/power_dist_v1-<hash>.csv' CSV HEADER;
```

| Kolon | Kaynak |
|---|---|
| `genome_id` | `run_chain(..., genome_id=...)` ile verilir (§13.3 genome kimliği) |
| `ref` | Aynı parçanın tüm referansları, boşlukla ayrılmış (`C2 C6 C7`) |
| `part_number` | Şablondaki gerçek MPN; pasiflerde `deger_paket` (`100n_0603`) |
| `qty` | O satırdaki referans sayısı |
| `unit_cost_try` | Şablonun taşıdığı birim fiyat |
| `supplier` | Tedarikçi adı |
| `lead_time_days` | Tedarik süresi |

Satırların tek kaynağı şablonun parça listesidir: şematiği çizen liste ile
faturayı ödeyen liste aynıdır, bu yüzden ayrışamazlar.

## Sınır

Fiyat ve stok bilgisi şablonun kendi sayısıdır; **tedarikçiye sorulmaz.**
§13.2'nin "stok/fiyat kontrolü" adımı bu dosyada fiyatı veya tedarik süresi
olmayan satırı hata sayar, fakat canlı stok sorgusu yapmaz. Sipariş öncesi
fiyatlar insan gözden geçirmesinde doğrulanır (§13.2, atlanamaz adım).
