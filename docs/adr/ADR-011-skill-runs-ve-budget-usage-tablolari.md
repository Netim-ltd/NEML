<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-011 — §7'ye iki tablo: skill_runs ve budget_usage

**Durum:** Kabul edildi · **Tarih:** 2026-09-16 · **Kaynak:** NEML_SPEC.md §7, §14.2, §14.4, §14.6, §16 T-084
**Tür:** Spesifikasyon değişikliği — sahip kararı

## Bağlam

§14'ün iki mekanizması §7'de karşılığı olmayan veriye dayanıyordu:

1. "Bir skill'in son 20 koşusu" (§14.2 başarısızlık onarımı, §14.6 adım 4).
   §7'de tekil koşu kaydı yok; yalnızca skill_validations var ve o da
   trials/successes olarak toplulaştırılmış. sum(successes)/sum(trials)
   yaklaşımı "son 20 koşu" ile aynı şey değildir ve §11.2 kuralı 3'ü
   (deterministik olmayan koşu karara giremez) uygulayacak ayrıntıyı taşımaz.
2. Günlük bütçe sayaçları (§14.4). §7'de hiç bütçe tablosu yok. Sayaçlar süreç
   belleğinde tutuluyordu ve yeniden başlatmada sıfırlanıyordu; bu doğrudan
   T-084'ün "72 saat kesintisiz çalışma, bütçe aşımı yok" kriterini bozar.

## Karar

§7'ye iki tablo eklenir.

    CREATE TABLE skill_runs (
        id            BIGSERIAL PRIMARY KEY,
        skill_id      TEXT NOT NULL REFERENCES skills(id),
        task_run_id   BIGINT REFERENCES task_runs(id),
        env           TEXT NOT NULL CHECK (env IN ('sim','real')),
        seed          BIGINT,
        success       BOOLEAN NOT NULL,
        failure_mode  TEXT,
        deterministic BOOLEAN NOT NULL DEFAULT TRUE,
        run_at        TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ON skill_runs (skill_id, run_at DESC);

    CREATE TABLE budget_usage (
        day       DATE NOT NULL,
        resource  TEXT NOT NULL,
        used      NUMERIC(14,4) NOT NULL DEFAULT 0,
        PRIMARY KEY (day, resource)
    );

budget_usage tüketimi tek atomik ifadeyle yapılır:

    INSERT INTO budget_usage (day, resource, used) VALUES (:day, :res, :amt)
    ON CONFLICT (day, resource) DO UPDATE SET used = budget_usage.used + :amt
    RETURNING used;

Sıfırlama örtüktür: yeni gün yeni satırdır. Ayrı bir sıfırlama işi yazılmaz.

## Gerekçe

- skill_runs satır başına bir deneme tutar; "son 20 koşu" gerçek bir sorgu
  hâline gelir. deterministic false satırları sorgunun kendisinde elenir —
  §11.2 kuralı 3 çağıranın insafına bırakılmaz.
- Oku-sonra-yaz çifti burada gerçek bir hatadır, biçim tercihi değil: iki
  eşzamanlı tüketici aynı limiti birlikte geçebilir. Tek ifade bunu kapatır.
- budget_usage satırı tarih artı kaynak anahtarlıdır; gün dönümü veri yazmadan
  gerçekleşir, saat dilimi mantığı tek yerde (config/budget.yaml,
  Europe/Istanbul) kalır.

## Sonuçlar

- §7 şeması bu ADR ile genişlemiştir. Alembic 0003 migration'ı iki tabloyu
  ekler; neml_local ve neml_cloud aynı şemayı paylaştığı için ikisine de
  uygulanır.
- db/repo.py'deki eski skill_validations tabanlı yaklaşık başarı oranı
  silinmiştir. İki sözleşmenin yan yana yaşamasına izin verilmez (ADR-010 ile
  aynı gerekçe).
- runtime/budget.py sayaçları artık bu tablodan okur; süreç belleği bir
  önbellek bile değildir.
- skill_runs.failure_mode ADR-013'teki sabit listeden bir değer taşır.
