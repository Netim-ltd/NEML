<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-010 — Mekanik parametre şeması: template_id başına oneOf

**Durum:** Kabul edildi · **Tarih:** 2026-09-16 · **Kaynak:** NEML_SPEC.md §4.3, §12.1, §13.3
**Tür:** Spesifikasyon değişikliği — sahip kararı

## Bağlam

§4.3'teki param_mech şeması tek düz bir params nesnesidir ve
additionalProperties false taşır. Ancak aynı şema beş farklı şablona
(leg_link_v1, bracket_v1, foot_pad_v1, sensor_mount_v1, battery_tray_v1)
hizmet etmektedir. Uygulama sırasında bunun tutarsız olduğu ortaya çıktı:

- §12.1'deki leg_link_v1 gövdesi p["height_mm"] okuyor; şemada böyle bir alan
  yok. Şemaya uyan her nesne şablonda KeyError veriyor.
- §13.3'teki tohum genome'un foot_pad girdisi diameter_mm 32 ve material TPU
  içeriyor; şema ikisini de reddediyor (additionalProperties false ve
  PETG/PA6-CF/PLA/ASA enum'u).

Sonuç: tohum genome kendi parametre doldurma adımından üretilemiyordu.

## Karar

MECH_PARAM_SCHEMA, template_id üzerinden ayrışan bir oneOf olur. Her şablon
kendi parametre şemasını taşır. leg_link_v1 dalı height_mm kazanır;
foot_pad_v1 dalı diameter_mm kullanır ve material enum'u TPU'yu kabul eder.

Her dal additionalProperties false tutar, her sayısal alan sınırlı kalır, her
seçim enum olarak durur. §4.3'ün "şema dışı çıktı fiziksel olarak imkânsızdır"
garantisi aynen korunur.

TPU yalnızca yumuşak parçanın anlamlı olduğu dallarda (foot_pad_v1) bulunur;
TPU'dan yapısal bacak bağlantısı diye bir şey yoktur.

Şemanın tek kaynağı hardware/cad/templates altındaki SCHEMA tanımlarıdır;
llm/schemas.py oneOf'u bunlardan derler, yeniden yazmaz.

## Gerekçe

- Ayak pedinin uzunluğu, bacak bağlantısının çapı yoktur. Tek düz nesne beş
  farklı parçaya hizmet edemez: ya alanları gevşetirsiniz (şema anlamını
  yitirir) ya da dallandırırsınız.
- Alternatif "tek şemayı genişlet" değerlendirildi ve reddedildi: height_mm ve
  diameter_mm eklemek şemayı geçerli kılar ama model artık bir foot_pad için
  rib_count üretebilir. Şema anlamsız parametreleri engellemez hâle gelir.
- Alternatif "şablonları şemaya uydur" da reddedildi: TPU ayak pedi
  kaybedilirdi; yumuşak ayak pedi tutunma için gerçek bir tasarım tercihidir.
- İki ayrı yerde yaşayan aynı sözleşme birbirinden kayar. Hatanın kök nedeni
  buydu; tek tanım kuralı bu sınıfı tümüyle kapatır.

## Sonuçlar

- §4.3'teki şema tablosu bu ADR ile değişmiştir. NEML_SPEC.md güncellenene
  kadar bu dosya bağlayıcıdır.
- guided_json arka ucu (xgrammar) oneOf desteklemek zorundadır; desteği
  regresyon testiyle sabitlenmiştir.
- Yeni şablon eklemek hâlâ insan işidir (ADR-005); yeni şablon kendi
  SCHEMA'sını getirir ve oneOf'a otomatik katılır.
- §13.3 tohum genome artık kendi şemasından üretilebilir; bir testle
  sabitlenmiştir.
