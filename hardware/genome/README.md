<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Hardware Genome

Bu dizin, NEML_SPEC.md §13.3'teki donanım genomunu tutar.

| Dosya | Açıklama |
|---|---|
| `genome.schema.json` | §13.3 yapısının tamamı için JSON Schema (draft 2020-12). §18.2 kapı 5 bu şema ile doğrular. |
| `quadruped_v2.yaml` | §13.3 örneği — tohum (seed) genom. `cad_templates` parametreleri ADR-010 ile tamamlandı (aşağı bakınız). |

## §4.3 parametre şeması — sahip kararı ile değiştirildi (2026-09-16)

Proje sahibi 2026-09-16 tarihinde §4.3'teki `param_mech` şemasını değiştirdi
(ADR-010). Karar spesifikasyonun kendisi kadar bağlayıcıdır.

**Neden:** Tek düz bir `params` nesnesi beş farklı şablona hizmet edemiyordu.
Ayak pedinin uzunluğu, bacak bağlantısının çapı yoktur. Sonuç olarak §12.1'deki
`leg_link_v1` gövdesi şemada bulunmayan bir `height_mm` okuyor, §13.3'teki tohum
genom ise şemanın reddettiği bir `diameter_mm` ve `TPU` malzemesi kullanıyordu.
Tohum genom kendi parametre doldurma adımıyla **üretilemiyordu**.

**Yeni biçim:** `MECH_PARAM_SCHEMA` artık `template_id` üzerinden ayrışan bir
`oneOf`'tur. Her şablonun kendi parametre şeması vardır:

```json
{
  "type": "object",
  "oneOf": [
    {"properties": {"template_id": {"const": "leg_link_v1"},
                    "params": { "...leg_link_v1 kendi şeması..." }}},
    {"properties": {"template_id": {"const": "foot_pad_v1"},
                    "params": {"required": ["diameter_mm", "height_mm",
                                            "wall_mm", "material"]}}}
  ]
}
```

Değişmeyenler — §4.3'ün "şema dışı çıktı fiziksel olarak imkânsızdır" garantisi
aynen durur:

- Her dal `additionalProperties: false` taşır.
- Her sayısal alan alt ve üst sınırlıdır; her seçim bir `enum`'dur.
- `TPU` yalnızca yumuşak parçanın anlamlı olduğu dalda (`foot_pad_v1`) bulunur.
  Yapısal bir bacak bağlantısı TPU'dan basılmaz.
- Yeni şablon eklemek hâlâ insan işidir (§12.1).

**Tek kaynak kuralı:** Dalların tanımı `hardware/cad/templates/*.py` içindeki
`SCHEMA` sabitleridir. `brain/neml_brain/llm/schemas.py` `oneOf`'u bunlardan
**derler**, yeniden yazmaz. Hatanın kök nedeni aynı sözleşmenin iki kopyasının
birbirinden kaymasıydı; tek tanım bu hata sınıfını tümüyle kapatır.

**Tohum genom üzerindeki etkisi:** `cad_templates` girdileri artık ilgili
şablonun dalına göre doğrulanır (`brain/tests/generators/test_templates.py`).
§13.3 örneği parametreleri kısaltarak veriyordu; eksik olanlar (`height_mm`,
`infill_pct`, `material`) şablonların test edildiği değerlerle tamamlandı.
§13.3'te yazılı hiçbir değer değiştirilmedi. Bir genomdan geometri yeniden
üretilebilmesi için parametre kümesinin eksiksiz olması gerekir.

## `limits` bloğu evrime kapalıdır

```yaml
limits:
  joint_torque_nm_max: 2.5
  joint_velocity_rads_max: 6.0
  body_current_a_max: 20.0
  body_temp_c_max: 70.0
```

Bu blok **evrim döngüsünün arama uzayına dahil değildir**. Bir aday genom bu
değerleri değiştiremez, gevşetemez veya yeni bir limit anahtarı ekleyemez:

- Şema `limits` içinde `additionalProperties: false` kullanır; tanımsız bir
  limit anahtarı doğrulamayı düşürür (§18.2 kapı 5).
- Değişiklik denemesi **kodla** reddedilir; prompt veya konfigürasyon ile
  atlanamaz (§0.4, §0.7).
- Limit ihlali fitness'ta sert cezadır: `F = −1`, düşük puan değil (§14.3).
- Limitlerin fiziksel karşılığı L0 donanım güvenliğidir (§5.1); yazılım
  tarafındaki bu blok yalnızca ikinci savunma hattıdır.

Limit değişikliği **insan işidir**: bu dosya elle düzenlenir, gerekçe
`audit_log`'a yazılır ve yeni bir genom sürümü açılır.

## Değişmeyen diğer kurallar

- `hash` içerikten türetilir ve her artefaktta referans verilir (§0.6).
- `parent` soy ağacını kurar; `quadruped_v1@8e2bd40` biçimindedir.
- `performance` **ölçülen** değerlerdir, simülasyon çıktısı değildir.
- `body_mass_kg` ölçülen, `body_mass_cad_kg` CAD tahminidir; ikisi arasındaki
  fark %10'u aşarsa URDF doğrulaması düşer (§12.2).

## Doğrulama notu

YAML 1.1, tırnaksız `created: 2026-02-08` değerini `date` nesnesine çevirir.
Genom yükleyicisi, şema doğrulamasından önce tarihleri ISO-8601 **metnine**
çevirmelidir (`json.loads(json.dumps(genome, default=str))`); şema `created`
alanını metin olarak bekler.
