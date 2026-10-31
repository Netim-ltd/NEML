<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-005 — Kısıtlı üretim mimarisi: LLM kod yazmaz

**Durum:** Kabul edildi · **Tarih:** 2026-09-15 · **Kaynak:** NEML_SPEC.md §0.5, §4.3, §6.5

## Bağlam

Yaygın yaklaşım, LLM'e araç listesi ve serbest bir görev verip kod/çağrı
üretmesini beklemektir. NEML'in modeli 1.5B'dir (ADR-004) ve bu yaklaşımda
üretilen FreeCAD scripti, şematik ya da araç çağrısı güvenilmezdir. Üstelik
hata sessizdir: sözdizimi doğru ama geometri üretilemez olabilir.

## Karar

LLM **hiçbir zaman** serbest metin/kod üretmez. Üç aşamalı boru hattı
zorunludur (§4.3):

1. **Sınıflandır (LLM).** İstek sabit bir enum'a eşlenir. Çıktı
   `guided_choice` ile kısıtlanır — model başka bir şey üretemez. ~20 token.
2. **Parametre doldur (LLM).** İlgili niyetin JSON Schema'sına uyan bir nesne
   üretilir. `guided_json` ile şema **üretim zamanında** zorlanır; şema dışı
   çıktı fiziksel olarak imkânsızdır. ~150 token.
3. **Üret (deterministik).** JSON, elle yazılmış ve test edilmiş parametrik
   şablona verilir. Bu adımda **model yoktur**; çıktı %100 tekrarlanabilirdir.

Tek istisna `summarize` profilidir: çıktısı yalnızca insana gösterilir,
sisteme girmez (§4.4).

MCP çağrıları da LangGraph düğümleri tarafından **deterministik olarak**
yapılır. "Modele araç listesi ver, seçsin" yaklaşımı yasaktır (§6.5).

## Gerekçe

- Şema zaten geçerli çıktı garanti eder; model küçüklüğü **doğruluk riskini
  artırmaz**. Model yanlış parametre seçse bile geometri her zaman geçerli,
  üretilebilir ve şema-uyumludur. Yanlış parametre simülasyonda elenir.
- Doğrulama (üretim sonrası kontrol) ile kısıtlama (üretim zamanı garanti)
  aynı şey değildir. Kısıtlama, hatalı çıktının hiç var olmamasını sağlar.
- Deterministik şablonlar test edilebilir. LLM çıktısı test edilemez.

## Sonuçlar

- Her yeni parça tipi için **elle yazılmış bir şablon** gerekir. Şablon
  yoksa sistem o parçayı üretemez — bilinçli bir tavandır.
- Şablon kütüphanesi (`hardware/cad/templates/`) projenin gerçek değeridir;
  model değiştirilebilir, şablonlar kalır.
- §0.5 gereği bu karar sadeleştirilemez: "model kod yazsın" yönünde bir
  değişiklik yapılamaz.
- §19 risk 1 gerçekleşirse (model parametre doldurmada bile yetersiz)
  parametreler elle doldurulur, model yalnızca router olarak kalır; mimari
  değişmez.
