<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# neml_swarm

Faz 5 swarm katmanı (NEML_SPEC.md T-082, T-083). Üç düğüm:

| Düğüm | Nerede çalışır | Görevi |
|---|---|---|
| `swarm_coordinator` | Lab istasyonu | Filo görünümü + tavsiye niteliğinde dağıtım planı |
| `lease_agent` | Her robot | Kendi görevinin kirasını yeniler, düşen komşunun işini devralır |
| `link_guard` | Her robot | Bağlantı kaybında 2 s içinde güvenli duruma geçirir (T-083) |

## Neden kira (lease)?

§17.2 swarm'ı WiFi + zenoh üzerine koyar. Bir robot arıza anını kimseye
bildirmez; **susar**. Merkezî bir görev tablosu bu durumda iki şekilde yanılır:
ya robotu ölü ilan edip hâlâ çalışan bir robotun işini elinden alır, ya da
bölünme (partition) sırasında hiç kimse karar veremediği için iş askıda kalır.

Kira bu ikilemi ortadan kaldırır:

- Bir görevin sahibi olmak, **süresi dolan ve yenilenmesi gereken** bir kirayı
  elde tutmak demektir.
- Yenilemeyi kesen robot, sahipliği aynı anda ve her yerde kaybeder. Bunu
  kimsenin karar vermesine gerek yoktur; saat karar verir.
- Süresi dolmuş bir kirayı **komşu robot doğrudan alır**. Koordinatör izin
  vermez, çünkü koordinatör tam da kaybolan şey olabilir.

`swarm_coordinator` bu nedenle **broker değildir**. Süreci öldürün: devir
çalışmaya devam eder, yalnızca filo görünümü ve yük dengeleme kaybolur.

## Kuralların tamamı (`neml_swarm/lease.py`)

1. Kira `(task_id, holder, epoch, expires_at_s)`. Mesajla değil, saatle biter.
2. Yalnızca **süresi dolmuş** kira devralınabilir. Canlı kira reddedilir, yani
   birbirini duyabilen iki robot asla aynı görevin sahibi olmaz.
3. Devralma `epoch`'u bir artırır. Ölümden dönen eski sahip eski epoch ile
   yenileme yayınlarsa `merge` onu eler — dirilen robot görevi sessizce geri
   alamaz.
4. `merge`, `(epoch, expires_at_s, holder)` üzerinde **tam sıralamadır**. Aynı
   mesaj kümesini duyan her düğüm, mesajlar hangi sırayla gelirse gelsin aynı
   sahipte anlaşır. Tur atmaya (round trip) gerek yoktur.
5. Devralma talepleri göreve özel bir sırayla (`reclaim_delay_s`) kademelenir,
   böylece üç robot aynı milisaniyede aynı işe atlamaz. Kendi sırasını
   beklerken başkasının talebini duyan robot geri çekilir.

### Tavan

Bu bir **kira** mekanizmasıdır, konsensüs değildir. Birbirini duyamayan iki
robot aynı süresi dolmuş kirayı devralabilir — her ikisi de yalnızca sessizlik
görür ve sessizlik ölümden ayırt edilemez. Bölünme kapandığında `merge`
kazananı belirler, kaybeden kirasının elinden alındığını görür. Bu "kutuyu
taşı" için doğru, "aktüatörü bir kez ateşle" için yanlıştır. Bir görev
idempotent olmaktan çıkarsa çözüm TTL'i uzatmak **değil**, çoğunluk oylaması
(roster üzerinde raft) veya aktüatörün kontrol ettiği bir fencing token'dır.

## T-082 ile T-083 nasıl birleşir

`LEASE_TTL_S` bilerek T-083 süresine (2 s) eşittir ve `link_guard` bu sürenin
%80'inde (1.6 s) tetiklenir. Sıralama şudur:

```
t=0.0  bağlantı koptu
t=1.6  link_guard mandal ister      → `cmd/safety_trip` (REASON_LINK_LOSS)
t<2.0  mandal kapandığını bildirir  → robot durdu (T-083 kriteri: < 2 s)
t=2.0  kira süresi dolar            → komşu robot işi devralabilir (T-082)
```

Aradaki 0.4 s (`assignment.confirm_budget_s`) mandalın cevap verme payıdır.
`link_guard` tek bir mesaj yayınlayıp işini bitmiş saymaz: `state/safety`
üzerinde `latched=true` görene kadar istemeye devam eder. Sebebi basit —
`cmd/*` sınıfı RELIABLE ama VOLATILE'dır; o anda yeniden başlayan bir
`watchdog_monitor` ilk mesajı hiç duymaz ve robot, log "durdu" derken hareket
etmeye devam eder. Pay dolduğunda bu bir **T-083 ihlalidir** ve öyle loglanır;
bu düğüm gücü kesemez, yalnızca §5.1 L0 rölesi kesebilir.

Operatör mandalı açtığında `link_guard` yeniden kurulur ve bağlantıya
açılıştaki kadar (1.6 s) süre tanır. Koordinatör hâlâ yoksa tekrar tetikler:
T-083'ün sabırsız operatör istisnası yoktur. Koordinatörsüz tezgâh çalışması
`link_timeout_s` ile ayarlanır ya da bu düğüm hiç çalıştırılmaz.

Yani iş, **hâlâ hareket eden** bir robottan devralınmaz. `lease_agent` güvenlik
mandalı kapandığı anda yenilemeyi keser; bu, devri tam TTL beklemeden
hızlandırır.

## QoS (§17.2)

| Topic | Sınıf | Profil |
|---|---|---|
| `/swarm/telemetry/lease` | telemetry | BEST_EFFORT / VOLATILE / KEEP_LAST(1) |
| `/swarm/cmd/lease_claim` | cmd | RELIABLE / VOLATILE / KEEP_LAST(10) |
| `/swarm/tasks`, `/swarm/assignments`, `/swarm/coordinator_heartbeat` | cmd | RELIABLE / VOLATILE / KEEP_LAST(10) |
| `/<robot>/state/robot` | state | RELIABLE / TRANSIENT_LOCAL / KEEP_LAST(1) |
| `/<robot>/state/safety` | state | RELIABLE / TRANSIENT_LOCAL / KEEP_LAST(1) |
| `/<robot>/cmd/safety_trip` | cmd | RELIABLE / VOLATILE / KEEP_LAST(10) |

Yenileme kaybolabilir (bir periyot kaybı, TTL dört periyodu karşılar), devralma
talebi kaybolamaz — kaybolursa görev sahipsiz kalır. Ayrım tam olarak budur.

**Kamera kuralı (§17.2, bağlayıcı):** ham kamera akışı swarm ağına verilmez. Bu
paket hiçbir görüntü mesajına dokunmaz; tek çıkış yolu `neml_perception`'daki
kapıdır (JPEG, yalnızca abone varken). `test/test_assignment.py` bu paketin
kaynak ağacında `sensor_msgs` veya `camera` geçmediğini doğrular.

Aynı test dosyası her `create_publisher` / `create_subscription` çağrısını
AST ile okuyup yukarıdaki üç profilden birini kullandığını doğrular. rclpy
`qos_profile` yerine düz bir tamsayı kabul eder ve sessizce
RELIABLE/VOLATILE verir; bir `state` topic'inde bu, geç katılan abonenin
robotun mandallı olduğunu hiç öğrenememesi demektir.

## Test

Saf mantık (kira aritmetiği, devralma sırası, T-083 sayacı ve onay payı) ROS
olmadan koşar — paket dizininden `python -m pytest test`. Canlı grafik
gerektiren iki launch testi (`test_swarm_launch.py` = T-082 devri,
`test_link_guard_launch.py` = T-083 kronometresi) ROS 2 kurulu olmayan
makinelerde atlanır; Ubuntu ana makinede `colcon test` ile koşar.
