<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# CAD: tarif dili ve mühendislik araçları

NEML'de parça şablonla değil **tarifle** çizilir: model (ya da sen) bir JSON tarif yazar, `neml-mcp-cad` bunu doğrular ve FreeCAD'de çizer.
Tarif veridir; sunucu hiçbir şeyi çalıştırmaz. Birim mm, açı derece.

## Katılar (`solids`)

| `t` | Alanlar | Not |
|---|---|---|
| `box` | `at` (köşe), `size` [l,w,h] | |
| `cyl` | `at` (taban merkezi), `r`, `h`, `axis` | |
| `cone` | `at`, `r`, `r2`, `h`, `axis` | `r2: 0` sivri uç |
| `sphere` | `at` (merkez), `r` | |
| `prism` | `plane` xy/xz/yz, `pts`, `h`, `at` | 2B kesiti çıkar (extrude). `pts` yoksa `r` ile daire |
| `turn` | `plane`, `pts`, `about` u/v, `angle`, `at` | kesiti eksen etrafında döndür (revolve) |
| `loft` | `plane`, `pts`, `pts2`, `h`, `at` | iki kesit arası (aynı köşe sayısı) |
| `pipe` | `r`, `ri`, `path` [[x,y,z],…] | düz parçalar köşelerde küreyle birleşir; yumuşak büküm yok |
| `array` | `of`, `n`, `step` [dx,dy,dz] | doğrusal dizi |
| `polar` | `of`, `n`, `axis`, `at` (merkez), `angle` | dairesel dizi (cıvata dairesi) |
| `mirror` | `of`, `plane`, `at` | ayna kopyası; birleştirmek için `fuse` kullan |

**Eskiz.** `pts` köşe listesidir: `[u, v]`. Üçüncü sayı (`[u, v, bulge]`) o köşeden sonrakine **yay** çizer: `bulge = tan(açı/4)`,
`1` yarım daire, `0.4` yaklaşık çeyrek daire, eksi sayı ters yön. İki köşe `[[0,0,1],[20,0,1]]` bir daire yapar; kaplı oval (slot) için iki yarım daire ve iki doğru.

## Adımlar, özellikler, yuvarlama, ölçü sözü

- `steps`: `cut` ya da `fuse` (`a`, `b`, `out`). `result` son parçanın id'si.
- `features` (adımlardan sonra, sırayla):
  - `hole`: `kind` plain / cbore (alın) / csink (havşa, 90°) / tap (kılavuz); `at` yüzeydeki nokta, `axis`, `dir` (`-` malzemenin içine doğru), `d`, `depth` (yoksa boydan boya), `d2`+`depth2` (alın) ya da `d2` (havşa). `tap` için `d` bir metrik ölçü (M2…M12): delik kılavuz matkabıyla (ör. M4 → 3.3) açılır ve diş bilgisi sonuçta `threads` olarak döner (süs dişi, gerçek helis yok).
  - `shell`: `t` duvar, `open` açık yüz (`z+` …). İçi boşaltır.
- `round`: `kind` fillet/chamfer, `r`, `edges` all/vertical/top/bottom.
- `spec`: `[{axis, value, tol}]`. Lab ölçüp sonuçta `spec_checks` verir; tutmazsa üretim akışında model tarifi düzeltmek üzere geri çağrılır.

## Araçlar (MCP, `neml-mcp-cad`)

| Araç | Ne yapar |
|---|---|
| `build_recipe` | Tarifi çizer, STL+STEP+3MF yazar. Ölçüm döner: hacim, kütle merkezi, yüzey alanı, en ince duvar, havada kalan alan, `threads`, `spec_checks`. `process` (`print`/`cnc`) verilirse üretilebilirlik (DFM) önerileri `dfm` olarak gelir. |
| `drawing` | STEP'ten imalat resmi: üçüncü açı izdüşümü (ISO 5456-2), görünmeyen çizgiler kesikli, toplam ölçüler (+ istersen tolerans), delik/diş çıkıntıları, istersen taramalı **kesit**, başlık bloğu, standart ölçek (10:1 … 1:20) ve pafta (A4→A2). `<ad>.svg` ve `<ad>.dxf`. |
| `standard_part` | ISO 4762 vida, ISO 4032 somun, ISO 7089 pul, rulman (608, 6000, 6202 …), alüminyum profil (2020/3030/4040), normuna uygun ölçülerle. |
| `fit` | ISO 286 geçme: `H7/g6` gibi bir çift için delik ve mil sınırları, boşluk/sıkılık (1–250 mm). Delik harfleri D E F G H JS, mil harfleri d e f g h js k m n p, kalite 5–12. |
| `assemble` | Parçaları **eşleştirmeyle** yerleştirir (`stack`, `flush`, `align`, `offset`, `fixed`), çakışma hacmini ve yaklaşan parçalar arasındaki boşluğu raporlar, montaj STEP'i yazar. |
| `fem` | Gerçek tetrahedral ağ (gmsh, 2. derece) üzerinde lineer-elastik statik çözüm: yer değiştirme, von Mises gerilmesi, emniyet katsayısı. Bir yüz sabit (`fixed: "x-"`), bir yüze yük (`load: {face: "x+", force: [fx,fy,fz]}`). |
| `convert` | STEP/IGES → STL. |

Doğrulama: bir ucundan tutulan 60×6×6 mm PLA konsol, ucunda 5 N: FEM sehimi 0.949 mm, el hesabı 0.952 mm; gerilme 7.7 MPa, el hesabı 8.3 MPa.

**Panelden / asistandan.** `POST /api/v1/learning` ile `{"op":"cad","tool":"standard_part","args":{...}}` (tool: fit, standard_part, drawing, build_recipe, fem, assemble). Sonuç sayıları ve dosyaların medya adresleri (stl, step, svg, dxf) komut sonucunda döner; dosyalar labın kendi çalışma klasörüne yazılır.

## Yapım akışına bağlantı

Lab bir robotun her tasarlanan parçası için: tarifi çizer → ölçü sözünü (`spec`) kontrol eder → kiriş kontrolü yapar (çok inceyse kesiti 6/9/12 mm'ye kendisi kalınlaştırır) →
imalat resmini (SVG+DXF) üretir ve model detayına yükler. Yapım paketinde baskı listesi yanında çizim adı ve DFM uyarıları (ince duvar, tabla taşması, destek gerektiren alan) görünür.
DFM ve ölçü uyarıları **uyarıdır**, tasarımı engellemez; engelleyen yalnızca yapısal (kiriş) ve yerleşim hakemleridir.

## Bilinen sınırlar (bilerek)

- Eskiz **kısıtsızdır** (köşe ve yay): paralel, teğet, ölçü gibi kısıt çözücü yok. Parametre değiştirmek için tarifi yeniden yazmak gerekir.
- STEP çıktısı geometridir: ürün ve üretim bilgisi (PMI), GD&T (şekil/konum toleransı) ve malzeme etiketi taşımaz. Tolerans yalnızca resimde ve `spec`te yaşar.
- Resim: 3 görünüş + 1 kesit; toplam ölçüler otomatik, ayrıntı ölçüleri (delik konumu, adımlı çaplar) yok; yalnızca delik/diş çıkıntıları var. Sac büküm, kaynak sembolü, yüzey pürüzlülüğü yok.
- Montaj: kutu (bounding box) tabanlı eşleştirme, 90°'nin katı dönmeler; yüz/eksen eşleşmesi, hareketli bağlantı ve çarpışma yolu yok. Çakışma ve boşluk gerçek geometriden hesaplanır.
- DFM: en ince duvar, havada kalan alan, delik derinliği/çapı gibi sayılarla yargı; özellik tanıma yok.
- FEM: tek yük durumu, tek düz yüze yük, tek düz yüzde mesnet, küçük şekil değişimi. Gerilme Gauss noktalarından okunur: mesnet köşelerindeki tepeler ağ hatasıdır. 20 000 elemandan büyük ağ reddedilir (`mesh_mm` büyüt).
- Ölçüm: en ince duvar yüzeyden içeri ışın örneklemesiyle bulunur (en çok ~120 örnek), kesin değil, uyarı için yeterli.
