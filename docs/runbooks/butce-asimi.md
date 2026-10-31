<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Runbook — Günlük bütçe aşıldı

**Kaynak:** NEML_SPEC.md §14.4, §14.5 · **Önem:** Orta

Bütçeler her gün **00:00 Europe/Istanbul**'da sıfırlanır. %90'da bildirim
gider; limit dolduğunda ilgili istek reddedilir. **Bu bir arıza değildir,
tasarımdır.** Sistem asla boşta beklemez ama asla bütçe dışına da çıkmaz.

| Kaynak | Limit | Aşımda |
|---|---|---|
| GPU süresi (vLLM + visual sim) | 6 saat | Yeni LLM çağrısı reddedilir, kuyruk bekler |
| Simülasyon koşusu | 200 | Yeni sim reddedilir |
| Fiziksel robot çalışma | 3 saat | Sadece sim görevleri |
| Filament | 500 g | Baskı onayı reddedilir |
| PCB siparişi | 1 / ay | Onay reddedilir |
| LLM token | 500.000 | Reddedilir |

## 1. Durumu gör

```bash
nemlctl status              # bütçe çubukları
curl localhost:8080/v1/budget
```

Prometheus: `neml_budget_used_ratio` — hangi kaynak, ne oranda.

## 2. Aşımın normal mi anormal mi olduğunu ayır

| Soru | Normal | Anormal |
|---|---|---|
| Aşım gün sonuna doğru mu oldu? | Evet | Sabah 10'da GPU 6 saati dolduysa hayır |
| Kampanya planlı mıydı? | Evet | Plansız tekrar koşular varsa hayır |
| `visual` profil kullanımı arttı mı? | Beklenen bir algı işi varsa evet | Yoksa hayır |
| Aynı görev tekrar tekrar mı koşuyor? | — | **Döngü var** |

**Anormalse önce döngüyü ara.** En sık kaynak: başarısız bir görev
`repair` üretiyor, `repair` de başarısız oluyor ve döngü kapanmıyor (§14.6).

## 3. Kaynağa göre eylem

### GPU süresi / LLM token doldu
- Kuyruk bekler, bu doğrudur. Acil bir iş varsa önceliği düşük görevleri
  iptal et, limiti yükseltme.
- `visual` profil kullanımını incele: her koşu ~40 s vLLM yeniden başlatma
  maliyeti getirir (§4.5). Gereksiz `visual` koşular varsa `fast`'e al.

### Simülasyon koşusu doldu
- Kampanya ayarlarına bak: nesil başına birey sayısı ve tekrar sayısı
  makul mu? Domain randomization ile 200 koşu hızlı tükenir.

### Fiziksel robot süresi doldu
- Sistem otomatik olarak yalnızca sim görevlerine döner. Bu beklenen
  davranıştır; fiziksel iş yarına planlanır.

### Filament doldu
- Baskı onayı reddedilir. Kuyruktaki baskıları önceliklendir, gereksiz
  iterasyonları iptal et.

### PCB siparişi (aylık) doldu
- Onay reddedilir. Revizyonu biriktir; §19 risk 9 gereği hazır modül
  kullanmayı değerlendir.

## 4. Limit değiştirme

`config/budget.yaml` düzenlenir. **Kural:** limit yükseltmek bir karardır,
bir refleks değildir. Yükseltmeden önce şu üçünü yaz:

1. Neden bu limit yetmiyor (ölçümle, tahminle değil).
2. Yeni limitin fiziksel/parasal karşılığı nedir.
3. Neyi feda ediyorsun (elektrik, filament, yazıcı ömrü, zaman).

Değişiklik `audit_log`'a düşer ve `CHANGELOG.md`'ye yazılır.

## 5. Boşta kalma davranışı (§14.5)

Bütçe dolduğunda sistem durmaz, sırayla ucuz işlere geçer: batarya < %30 ise
şarj, kapsam boşluğu varsa `exploration`, aktif kampanya varsa sonraki nesil,
kalibrasyon eskiyse `calibration`, hiçbiri yoksa son 24 saatin başarısızlık
loglarını gömüp `memory_chunks`'a yazar, o da bittiyse 60 s uyur.
