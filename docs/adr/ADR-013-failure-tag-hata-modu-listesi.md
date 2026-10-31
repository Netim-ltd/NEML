<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-013 — failure_tag hata modu listesi sabitlendi

**Durum:** Kabul edildi · **Tarih:** 2026-09-16 · **Kaynak:** NEML_SPEC.md §4.4, §14.6, §7
**Tür:** Spesifikasyon değişikliği — sahip kararı

## Bağlam

§4.4'teki failure_tag profili guided_choice ile kısıtlıdır, yani sabit bir
enum listesi gerektirir. Spesifikasyon bu listeyi hiçbir yerde vermez: §14.6
adım 2 profili çağırır ama modları saymaz, skill_validations.failure_modes de
serbest JSONB'dir.

Uygulama sırasında iki ayrı agent kendi listesini uydurdu. Aynı sözleşmenin
iki kopyası, kaçınılmaz olarak birbirinden kayacaktı.

## Karar

Liste sabittir ve ağaçta tek bir yerde tanımlıdır:

    FAILURE_MODES = [
        "joint_limit_hit",    # eklem limite dayandi
        "torque_saturation",  # tork doydu
        "balance_lost",       # denge kaybi / devrilme
        "foot_slip",          # ayak kaymasi
        "collision",          # beklenmeyen temas
        "goal_not_reached",   # hedefe varilamadi
        "timeout",            # sure asimi
        "sensor_dropout",     # sensor verisi kesildi
        "power_brownout",     # gerilim cokmesi
        "unknown",            # siniflandirilamadi
    ]

Tanım, kısıtladığı profille birlikte brain/neml_brain/llm/profiles.py içinde
yaşar; config/llm.yaml'a yansıtılır ki kısıt konfigürasyonda görünür olsun.
agents/reflection.py ve autonomy/learning.py bunu import eder, kopyalamaz.

## Gerekçe

- On mod dört bacaklı bir robotun gerçekten başarısız olma biçimlerini kapsar:
  mekanik (eklem, tork), denge (devrilme, kayma), görev (hedef, süre), algı
  (sensör), güç (gerilim).
- "unknown" kasıtlıdır. Kaçış vanası olmayan kapalı bir enum'da 1.5B model
  yanlış bir etiketi zorlar; yanlış etiket, etiketsizlikten kötüdür çünkü
  §14.6 adım 5'teki otomatik onarım görevini yanlış yöne sürer.
- Daha dar bir beş modlu liste değerlendirildi (sınıflandırma doğruluğu yüksek
  olurdu) ama §14.2'nin onarım görevi hata moduna göre parametre araması
  yapar; hardware_fault gibi geniş bir etiket arama uzayını daraltmaz, yani
  mekanizmanın değerini düşürürdü.

## Sonuçlar

- §4.4'teki failure_tag satırı bu listeyle tamamlanmıştır.
- skill_runs.failure_mode (ADR-011) bu değerlerden birini taşır.
- Listeye mod eklemek insan işidir ve bu ADR'nin güncellenmesini gerektirir;
  guided_choice listesi çalışma zamanında genişletilemez.
- Ağaçta ikinci bir kopya oluşmasını engelleyen bir test vardır; bu
  duplikasyon bir kez zaten yaşandı.
