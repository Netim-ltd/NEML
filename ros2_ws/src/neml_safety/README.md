<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# neml_safety

`watchdog_monitor` düğümü, NEML_SPEC.md §5.1'deki L0 güvenlik zincirinin
**yazılım aynasıdır**. Görevi olayı raporlamak ve yığındaki her şeyi durdurmak;
gücü kesmek değildir.

## Bu düğüm neyin yerine geçmez

> **Motor gücünü kesen şey donanımdır.**
>
> - E-stop, normalde kapalı (NC) bir mantar butondur ve motor gücünü **röle
>   ile** keser. Devre açıldığı anda güç gider; hiçbir yazılımın onayına
>   ihtiyaç duymaz.
> - ATmega328P watchdog MCU'su, ana kontrolcüden 50 ms'de bir heartbeat bekler.
>   150 ms boyunca heartbeat gelmezse motor rölesini **kendi başına** açar.
> - 20 A akım kesmesi donanımsal shunt + komparatördür. Yazılım değiştiremez.
>
> Bu düğüm çökse, hiç başlamasa veya sonsuz döngüye girse bile yukarıdaki üç
> koruma çalışır. Tersi doğru değildir: bu düğüm hiçbir koşulda röle, watchdog
> MCU'su veya komparatör yerine kullanılamaz. Bir montajda bunlardan biri
> eksikse, `neml_safety` çalışıyor olması gerekçe değildir.

## Ne yapar

- Hareket kontrolcüsünün yayınladığı heartbeat'i ve e-stop hattını dinler
  (ATmega'nın izlediği aynı sinyaller).
- `neml_msgs/SafetyStatus` yayınlar: mandal durumu, sebep, heartbeat yaşı.
- `cmd/motor_enable` üzerinden tüm yığına tek bit'lik durdurma sinyali basar.
  Kontrolcüler ve swarm koordinatörü buna abone olur.
- Mandalı **kilitler**. Sebep ortadan kalksa bile kendiliğinden açılmaz.
- Açılması için operatörün `safety/reset` servisini çağırması gerekir; servis,
  sebep hâlâ duruyorsa (e-stop basılı, heartbeat yok) reddeder.

## Beyinden bağımsızlık

Düğüm `neml-brain`'i import etmez, LLM'e sormaz, ağa çıkmaz. `safety.launch.py`
ile kendi sürecinde çalışır. Beyin çökerse mandal kapalı kalmaya ve durum
yayınlamaya devam eder.

## T-074 bütçesi

E-stop basılmasından `motors_enabled=false` mesajının hatta çıkmasına kadar en
kötü durum ~17 ms: 10 ms yardımcı MCU örnekleme periyodu + ~1 ms taşıma + 5 ms
değerlendirme timer'ı + ~1 ms yayın. Kabul kriteri 50 ms; 33 ms pay kalır.
E-stop geldiğinde timer beklenmez, yayın callback içinde yapılır.

### Nasıl ölçülür

50 ms bir yorum değil, bir sayıdır; bu yüzden ölçülür.

- **Saat:** `neml_safety/propagation.py` içindeki `now_ns()`, yani
  `time.monotonic_ns()`. ROS saati **kullanılmaz**: `use_sim_time` açıkken o
  saat simülasyonun saatidir ve hızlı bir simülasyonun üretebildiği gecikme
  değeri hiçbir şey ifade etmez. Düğümün `header.stamp` alanı sıralama ve log
  içindir, bütçe için değildir.
- **Giriş (ingress):** olay yazılım için var olduğu ilk an. `_on_estop` /
  `_on_trip` callback'inin ilk satırında `Trace(now_ns())` açılır.
- **Her abone:** kendi callback'inin ilk satırında `now_ns()` damgalar ve
  `trace.record("<abone adı>", damga)` ile aynı `Trace`'e ekler.
  `trace.breakdown()` bütçeyi yiyen hop'un adını söyler.
- **CLOCK_MONOTONIC makine geneli** olduğundan tek robot üzerindeki süreçler
  arasında damgalar doğrudan karşılaştırılabilir — T-074 zinciri zaten tek
  makinede koşar. İki robot arasında karşılaştırılamaz ve bu modül böyle bir
  iddiada bulunmaz.
- **Uçtan uca test:** `test/test_propagation_launch.py` gerçek grafiği ayağa
  kaldırır, e-stop'u hatta koymadan hemen önce damgalar, abone callback'inde
  tekrar damgalar ve farkı `ESTOP_BUDGET_MS`'e karşı iddia eder. Muhasebenin
  kendisi (`test/test_propagation.py`) ROS'suz koşar.
- Bu ölçüm **yalnızca yazılım ayağını** kapsar. Yardımcı MCU örnekleme
  periyodu ve motor rölesi donanımdır; onlar T-075'te osiloskopla ölçülür.
  Buradaki yeşil koşu o ölçümün yerine geçmez.

Düğüm her mandallanma olayında bunu kendisi de yapar: bütçe aşılırsa hop
kırılımıyla birlikte `error` seviyesinde loglanır, son `Trace` düğüm üzerinde
`last_trace` olarak durur.

## Çalışma öncesi zorunluluk

§5.1: her fiziksel çalışma oturumundan önce e-stop ve watchdog testi yapılır ve
`safety_checks` tablosuna yazılır. Kayıt yoksa `neml-brain` fiziksel görev
başlatmayı reddeder. Testi `neml_msgs/RunSelfTest` servisi ile koşun.
