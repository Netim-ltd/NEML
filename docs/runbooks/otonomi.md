<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Runbook: otonomi döngüsü

Döngü (`python -m neml_brain.autonomy`) kuyruktaki görevi alır, çalıştırır, **yargılar** ve
sonucu düzeltir. Yalnızca **simülasyon** yapar (ADR-014); robotu hareket ettirecek her şey
onay bekler.

## Açma / kapama

| Ne | Nasıl |
|---|---|
| Varsayılan | Kapalı. Süreç çalışır ama bekler (`autonomy.disabled`). |
| Aç (Docker) | `.env` içine `NEML_AUTONOMY_ENABLED=true`, sonra `docker compose -f docker/compose.control.yml -f docker/compose.autonomy.yml --profile autonomy up -d autonomy` |
| Aç (systemd) | `deploy/systemd/neml-autonomy.service` kurulur, `/etc/neml/autonomy.env` içine `NEML_AUTONOMY_ENABLED=true` |
| Kapat | `NEML_AUTONOMY_ENABLED=false` ve servisi yeniden başlat |
| Fiziksel mod | **Yok.** `NEML_AUTONOMY_MODE=physical` açılışta reddedilir |

## Bir görev nasıl biter

1. **Çalıştırma:** `human` → orkestratör; `world_id` taşıyan sim görevi → `sim.run_once`;
   `maintenance/calibration/repair/evolution` ya da robotlu görev → **park** (aşağıda).
2. **Yargı** (`autonomy/judge.py`): yürütücünün "başarılı" demesi yetmez. Kabul ölçütleri
   (görev `spec.acceptance` ya da türün varsayılanı) ve bağımsız kanıt aranır.
3. **Düzeltme:**
   - `accept` → görev `succeeded`
   - `retry` → aynı görev, yeni seed + hata etiketiyle yeniden kuyruğa (en çok 3 deneme)
   - `repair` → deneme bitti ve bir beceri var: onarım görevi açılır
   - `escalate` → güvenlik ihlali, bağımsız sensör kanıtı yok ya da çare kalmadı: görev
     `failed`, sahibe bildirim (`audit_log` → `task_escalated`)
4. **Gözden geçirme** (günde bir): son 7 günde `succeeded` olan görevler bugünkü ölçütlere
   göre yeniden yargılanır; geçemeyen **yeniden açılır**.
5. **Kendini ayarlama** (günde bir): öncelik formülünün spec'te verilmeyen çarpanları
   (`expected_gain`, `cheapness`) yargılanmış koşulardan yeniden uydurulur
   (`autonomy_tuning` tablosu). Geçmiş yokken başlangıç değerleri geçerli.

## Park edilen görevler

| Durum | Anlamı | Ne yapmalı |
|---|---|---|
| `paused`, `result.parked` dolu | Bu tür için otonom yürütücü yok | Sahip elle yürütür ya da görevi iptal eder |
| `awaiting_approval` | Robot gerekiyor; seviye 4 onay satırı açıldı | Uygulamadan onayla/reddet; fiziksel yürütme yine SAFETY.md kapılarından geçer |

## Bakılacak yerler

```sql
SELECT t.title, t.state, v.done, v.action, v.reasons
FROM task_verdicts v JOIN task_runs r ON r.id = v.task_run_id JOIN tasks t ON t.id = r.task_id
ORDER BY v.judged_at DESC LIMIT 20;

SELECT * FROM autonomy_tuning;   -- ayarlanan çarpanlar
```

## MTBF bakım kararı

`mtbf_min_hours` yönetici ekranından (Ayarlar → Robot modeli ayarları) girilmeden MTBF
kaynaklı bakım görevi **açılmaz**; sistem sayı uydurmaz. Girildiğinde: en az 2 arıza ve
fiziksel çalışma saatinden hesaplanan MTBF, eşiğin altındaysa `maintenance` görevi doğar.
