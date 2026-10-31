<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-014 — Spesifikasyon çelişki ve boşluklarının kararı

**Durum:** Kabul edildi (sahip: "sen karar ver", 2026-10-03) · **Tarih:** 2026-10-03 · **Kaynak:** `docs/SPEC_BULGULARI.md`
**Tür:** Spesifikasyon değişikliği — varsayılan kararlar

`NEML_SPEC.md` metni değiştirilmedi; bu ADR onu geçersiz kılar. Sahip aksini
söylerse yalnızca ilgili satırdaki kod geri alınır.

| # | Konu | Karar | Gerekçe |
|---|---|---|---|
| 1 | `approvals` tablosu | Lab ve bulut ortak. `CLOUD_ONLY = {users, devices, commands}` kalır. | Onay kapısı labda kodla zorlanır (§5.2); tablo labda olmadan kapı çalışamaz. |
| 2 | §14.4 başlığı "günlük" | Başlık "dönemlik" okunur. `pcb_orders` aylık, diğer beşi günlüktür. | Tablo ve `config/budget.yaml` zaten böyle. |
| 3 | `from_freecad_inertia` | Üç argüman (`inertia, mass_kg, volume_mm3`). | FreeCAD tensörü birim yoğunlukta mm⁵; kütle tek başına ölçekleyemez. |
| 4 | PARAM_FILL görev dalı | Görev dalı da guided_json ile doldurulur (`TASK_FILL`: `title`, `priority`, `task_id`). | Doğal dille görev kimliği ve öncelik çıkarılamıyordu. |
| 5 | VALIDATE → SIMULATE | Başarısız doğrulama simülasyonu atlar, doğrudan APPROVAL'a gider ve `validation failed` ile reddedilir. Mekanik ajan için §12.3 DFM kapısı (`validate_dfm`) VALIDATE'te çalışır. | Yapılamayacak parçaya sim bütçesi harcanmaz. |
| 6 | Bridge düşürme kuralı | Yalnızca `telemetry` düşer; event, ack, state, approval, log asla. | En dar okuma; veri kaybı yalnızca telemetride. |
| 7 | `param_ranges` ayrık/sürekli | Genome `mechanical.discrete: [anahtar]` listesi taşıyabilir; listedekiler mutasyona uğramaz. Liste yoksa eski ±%10 yuvarlama sezgisi geçerli. | Açık işaret, sezgiden güvenlidir. |
| 8 | `normalize()` bandı | `[0, 2×baseline]`; aktif genom 0.5'tedir. | Spesifikasyon yalnızca çapayı verir. |
| 9 | Gap toplaması | Önce manevra içindeki büyüklükler, sonra beş manevra ortalaması. | Her manevra eşit ağırlıkta. |
| 10 | `max_temp_c` | Hotend (M104/M109). Yatak `max_bed_temp_c` olarak ayrı raporlanır (M140/M190). | Tekil "max sıcaklık" belirsizdi; ikisi de görünür. |
| 11 | `FILAMENT_TRY_PER_G` | Yalnızca maliyet satırı olmayan elle yazılmış G-code için yedek. Gerçek fiyat dilimleyici profilinden gelir. | Tek sayı dört malzemeye yetmez, ama yedek yoldur. |
| 12 | `physics` | `POST /v1/sim/run` kabul eder; `spawn_robot`'ta uygulanır, `sim_version`'a girer. | T-077 kalibrasyonu için. |
| 13 | `refresh_tokens` | Yalnızca `neml_cloud` (EF migration). Alembic'e eklenmez. | Cloud-only tablo. |
| 14 | `NEML_OWNERS` | Anahtar `.env` şablonlarındadır, değer insana aittir. Boşken seviye 4 kapalıdır. | Güvenlik: fail-closed. |

## İkinci tur (2026-10-03): sahibin yönergeleri

| # | Konu | Karar | Gerekçe |
|---|---|---|---|
| 15 | Otonomi döngüsü | Servis olarak çalışır (`python -m neml_brain.autonomy`), **yalnızca simülasyon**, varsayılan kapalı. Fiziksel mod açılışta reddedilir. | SAFETY.md kapıları robota bağlı bir yürütücüde test edilmeden otonom hareket yok. |
| 16 | "Görev yapıldı mı?" | Deterministik yargıç (`autonomy/judge.py`): yürütücünün iddiası kabul ölçütleri ve bağımsız kanıtla doğrulanır; karar `accept/retry/repair/escalate`. Günlük gözden geçirme biten işi yeniden yargılar. | 1.5B model başarıyı yargılamamalı; yalnızca hata etiketlemeye yardım eder. |
| 17 | Spec'in vermediği çarpanlar | `expected_gain` ve `cheapness` yargılanmış koşulardan her gün yeniden uydurulur (`autonomy_tuning`), önceye doğru büzülür. | Sahip sürekli sayı girmeyecek. |
| 18 | MTBF ve modele özgü değerler | Yönetici ekranında model başına alanlar: **zorunlu** (`mtbf_min_hours`, malzeme fiyatları) ve **önerilen** (varsayılanlı). Zorunlu alan boşken o karar verilmez. | MTBF modelden modele değişir; sayı uydurulmaz. |
| 19 | Filament fiyatı | 600 TRY/kg (yedek 0.6 TRY/g, dört profil `filament_cost = 600`). Yönetici ekranında malzeme başına düzenlenir. | Sahibin verdiği değer. |
| 20 | Köprü sözleşmesi | .NET'in camelCase yükleri esas alındı. Beyin `command` mesajlarını uygular ve `command_ack` döner; bekleyen onayları `approval_request` ile duyurur; canlı akışı (BrainStatus, robot durumu, görev, telemetri) gönderir. | Önceden beyin komutları yalnızca logluyordu ve bulutun okuyamadığı şekillerde veri yolluyordu. |
| 21 | Fetch MCP | Kendi sunucumuz (`neml_mcp_fetch`, port 9109): https, izin listesi, her yönlendirmede yeniden kontrol, yalnızca metin. İsteğe bağlı: control düğümünde kapalıysa `off`. | Üst akım sunucusu doğrulanmadı, izin listesi sunucuda zorlanmalı. |
| 22 | ROS 2 / Docker / OpenSCAD MCP | **Alınmadı.** | `ros_gz` köprüsü sim yolunu kapsıyor; vLLM start/stop `GpuLock` ile yapılıyor; CAD için FreeCAD kararlı. |
| 23 | Güvenlik oturum kaydı | `nemlctl robot safety-check` ve `POST /v1/robots/{id}/safety-check`; üç bayrak zorunlu, başarısız kayıt da yazılır. | `safety_checks`'e yazan hiçbir araç yoktu; fiziksel oturum asla yetkilenemezdi. |
| 24 | BMS arıza hattı | Güç kartında `J30` (giriş), `R9` pull-up, `J31` (aux MCU'ya). Harness kontrolü SAFETY.md listesinde. | GPIO18 hattının bir yere bağlanması gerekiyordu. |

## Hâlâ insan girdisi isteyenler

`mtbf_min_hours` (yönetici ekranından, model başına) ve `NEML_OWNERS` değeri. Filament
fiyatı, subprocess izin listesi ve keşif sabitleri artık kapandı.
