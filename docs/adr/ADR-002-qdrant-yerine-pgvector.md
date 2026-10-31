<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-002 — Qdrant kullanılmayacak, vektörler pgvector'de

**Durum:** Kabul edildi · **Tarih:** 2026-09-15 · **Kaynak:** NEML_SPEC.md §2, §4.6, §7

## Bağlam

Sistem, başarısızlık loglarını ve bağlam parçalarını gömüp (`memory_chunks`,
§14.6) benzerlik araması yapmak zorundadır. Gömme boyutu 384'tür
(`intfloat/multilingual-e5-small`, §4.6). Ayrıntılı vektör veritabanları
(Qdrant, Milvus, Weaviate) daha zengin filtreleme ve ölçeklenme sunar.

## Karar

Ayrı bir vektör veritabanı **kurulmayacaktır**. Vektörler PostgreSQL 16
üzerinde `pgvector` ile `vector(384)` sütunu + HNSW indeksi olarak
saklanacaktır. Tek veri deposu vardır.

## Gerekçe

- Vektör hacmi laboratuvar ölçeğindedir (bir laboratuvarın deney kayıtları),
  milyarlarca değil. pgvector + HNSW bu ölçekte fazlasıyla yeterlidir.
- En değerli sorgular **karma** sorgulardır: "şu genome sürümünde, şu skill
  için, son 30 günde başarısız koşuların benzerleri". Bu sorgu pgvector ile
  tek `JOIN`'dir; ayrı bir vektör deposuyla iki sistem arasında elle
  birleştirme gerektirir.
- İkinci bir veri deposu ikinci bir yedekleme, ikinci bir tutarlılık sınırı
  ve ikinci bir hata modu demektir. Lab istasyonu tek makinedir.

## Sonuçlar

- Gömme yazma ve arama yolu Alembic migration'larının içindedir; şema
  değişikliği tek yerden yönetilir.
- HNSW indeks parametreleri (`m`, `ef_construction`) büyüdükçe ayarlanmalıdır;
  bu bir ayar işi, mimari değişiklik değildir.
- Vektör hacmi PostgreSQL'i zorlarsa çözüm önce partisyonlama ve saklama
  süresini kısaltmaktır (§18.3, §19 risk 10); ayrı bir vektör deposu son
  çaredir ve o noktada bu ADR yeniden değerlendirilir.
