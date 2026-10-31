<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Üretici tasarım kuralı dosyaları (NEML_SPEC.md §13.2)

`§13.2` doğrulama zincirinde DRC adımı **üretici kural dosyası ile** çalışır.
Bu klasördeki iki dosya `kicad-cli pcb drc` çağrısına verilen kural setidir:

| Dosya | Üretici | Süreç |
|---|---|---|
| `jlcpcb_2layer.kicad_dru` | JLCPCB | 2 katman, 1 oz bakır, HASL/ENIG |
| `pcbway_2layer.kicad_dru` | PCBWay | 2 katman, 1 oz bakır, HASL/ENIG |

`brain/neml_brain/generators/elec.py` varsayılan olarak JLCPCB dosyasını
kullanır; `run_chain(..., dru=...)` ile diğerine geçilir. Dosya yoksa zincir
`drc` aşamasında durur, sessizce devam etmez.

## ⚠ Sipariş öncesi zorunlu kontrol

**Bu değerler üreticinin yayımladığı yetenek tablosundan elle aktarılmıştır ve
üretici bunları haber vermeden değiştirir.** Her siparişten önce:

1. Üreticinin güncel "PCB Capabilities" sayfasını açın.
2. Aşağıdaki altı satırı tek tek karşılaştırın:
   - minimum iz genişliği ve iz aralığı (`track_width`, `clearance`)
   - minimum delik çapı ve delikler arası mesafe (`hole_size`, `hole_to_hole`)
   - minimum halka genişliği (`annular_width`)
   - bakır-kart kenarı mesafesi (`edge_clearance`)
   - serigrafi yazı yüksekliği/kalınlığı (`text_height`, `text_thickness`)
   - maske barajı (`physical_clearance`, pad-pad)
3. Fark varsa **önce bu dosyayı güncelleyin**, sonra DRC'yi tekrar çalıştırın.

Bu kontrol §13.2'deki "İNSAN GÖZDEN GEÇİRME — atlanamaz" adımının parçasıdır.
PCB siparişi geri alınamaz ve hatalı bir kural dosyası 2-3 hafta kaybettirir.

## Kapsam dışı

Çok katman, empedans kontrollü yığın, gömülü/kör via, 2 oz üstü bakır:
§13.1 gereği NEML bu sınıfları üretmez. `no buried or blind vias` kuralı bunu
DRC tarafında da bir hata hâline getirir.
