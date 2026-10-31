<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# stm32_motion — hareket kontrolcüsü (STM32F446RE + micro-ROS)

**Sürüm:** v1.4.2 (`NEML_SPEC.md` §13.3 `electronics.motion_controller.firmware`)
**Kontrat:** §2 (MCU hareket), §5.1 (limitler), §13.3, §16 T-072, §17.2 (ROS/QoS)

1 kHz kontrol döngüsü, micro-ROS üzerinden `JointTelemetry` yayını, ATmega328P
watchdog'una kalp atışı. HAL olarak **STM32Cube HAL** kullanılır.

> **Neden ST HAL, libopencm3 değil:** libopencm3 LGPL-3.0'dır. §1.3 kopyalef
> lisanslı kaynağın bu ağaca girmesini yasaklar ve deponun kendi pre-commit
> kapısı (`no-copyleft-source`) böyle bir dosyayı zaten reddeder. STM32CubeF4
> BSD-3-Clause'dur ve ayrıca ağaca kopyalanmaz, dışarıdan referans verilir.

---

## 1. Tork ve hız limiti — derleme zamanı sabiti

`firmware/neml_limits.h` (her üç firmware projesinin ortak limit başlığı):

```c
#define MAX_TORQUE_NM      2.5f   // SPEC 5.1, birebir
#define MAX_JOINT_VEL_RADS 6.0f   // SPEC 13.3 limits.joint_velocity_rads_max
```

Bunlar **konfigürasyon değildir**. Değeri yükselten hiçbir çalışma zamanı yolu
yoktur: ROS parametresi yok, topic yok, servis yok, flash hücresi yok, genome
alanı yok. Aynı dosyadaki `_Static_assert`'ler bu sabitleri §13.3 `limits`
bloğuna bağlar; biri kayarsa **derleme durur**:

```c
_Static_assert((int)(MAX_TORQUE_NM * 1000.0f) == LIMIT_JOINT_TORQUE_MNM, ...);
_Static_assert(LIMIT_JOINT_TORQUE_MNM < STS3215_STALL_TORQUE_MNM, ...);
```

Limit **iki yerde** uygulanır:

1. `control_step()` her tikte çıkışı `±MAX_TORQUE_NM`'ye kırpar.
2. Açılışta servo zincirine kendi akım limiti yazılır
   (`STS_TORQUE_LIMIT_PERMILLE` = 862‰ = 2.5/2.9). Böylece bu firmware'de bir
   hata olsa bile tavan ayakta kalır.

Limiti değiştirmek = bu dosyayı düzenlemek + yeniden derlemek + bir **insanın**
`make flash` çalıştırması (§5.2 Seviye 4 onayı, §5.4 `firmware.flash`).
Evrim döngüsü bu bloğa dokunamaz (§13.3 "limits: L4 DEĞİŞTİREMEZ").

---

## 2. Gerçek zaman bütçesi (1 ms tik)

180 MHz'de bir tik = 180 000 çevrim. `DWT->CYCCNT` ile ölçülür ve
`telemetry/motion_health` üzerinden `loop_max_us` olarak yayınlanır (§5).

| Adım | En kötü durum |
|---|---|
| `control_tick` + `control_step`, 16 eklem | ~22 µs |
| Servo hedef paketi kurulumu (120 bayt) | ~8 µs |
| Telemetri anlık görüntüsü (seqlock) | ~2 µs |
| Kalp atışı, bus watchdog, DWT muhasebesi | ~2 µs |
| **Toplam** | **~34 µs — tikin %3.4'ü** |

Bütçe sınırı 800 µs'dir; aşılırsa `CTRL_FAULT_TICK_OVERRUN` kalkar ve
`tick_overruns` sayacı artar. Kurallar:

- Kontrol yolunda **malloc yok**. `_sbrk` micro-ROS oturumu kurulduktan sonra
  kendini mühürler; sonraki her tahsis **başarısız döner** (`ENOMEM`) ve
  telemetride `CTRL_FAULT_HEAP` (0x40) olarak görünür. Trap edilmez: hatalı bir
  mesaj yüzünden hareket kontrolcüsünü düşürmek, o mesajı düşürmekten çok daha
  kötü bir arıza modudur — mesaj düşerse komut 100 ms'de eskir ve eklemler
  gevşer, ki zaten doğru cevap budur.
- Kontrol ISR'ında **sınırsız döngü yok**; her döngü `NEML_JOINT_COUNT` ile sınırlı.
- micro-ROS **asla** kontrol ISR'ında koşmaz. Arka plan döngüsündedir; veri
  aktarımı kilitsiz seqlock anlık görüntüsü ile yapılır (okuyucu 4 denemeden
  sonra vazgeçer — sınırlı).
- Kesme öncelikleri: TIM6 (kontrol) 0, servo bus 1, micro-ROS UART 2, SysTick 15.

---

## 3. Kalp atışı ve güvenli durum

`PA5`, 50 ms'de bir seviye değiştirir (§5.1) ve ATmega328P'ye gider.

**Kritik arıza mandallanırsa toggle durur** → watchdog 150 ms sonra motor
rölesini açar. Bu firmware motor gücünü kendisi kesemez ve kesmeye çalışmamalıdır;
L0 tasarım gereği yazılımdan bağımsızdır (§5.1).

| Arıza | Davranış |
|---|---|
| `CTRL_FAULT_ESTOP` (NC halka açık) | Mandallı kritik → tork 0, kalp atışı durur |
| `CTRL_FAULT_OVER_TEMP` (> 70 °C, §13.3) | Mandallı kritik → tork 0, kalp atışı durur |
| `CTRL_FAULT_NO_COMMAND` (> 100 ms) | Tork 0, eklemler ölçülen pozisyonu tutar. Mandallı değil |
| `CTRL_FAULT_TORQUE_CLAMPED` / `VEL_CLAMPED` | Yalnızca raporlanır — limit zaten uygulandı |
| `CTRL_FAULT_TICK_OVERRUN` | Raporlanır, öldürücü değil |

Mandal yalnızca reset ile temizlenir — tıpkı watchdog'daki gibi. Robotun kendi
kendine yeniden hareket etmeye başlaması kabul edilmez.

---

## 4. Pin bağlantıları

| Pin | İşlev |
|---|---|
| `PA5` | Kalp atışı çıkışı → ATmega328P `PD2` (ortak toprak zorunlu) |
| `PC13` | E-stop algılama, pull-up. NC halka kapalı = LOW. Kopan kablo = basılmış sayılır |
| `PA9` | USART1, yarım dupleks STS3215 servo zinciri, 1 Mbps, open-drain |
| `PA2` / `PA3` | USART2, micro-ROS ajanı (Raspberry Pi 5), 921600 baud |

---

## 5. ROS 2 arayüzü

Namespace derleme zamanında verilir (`-DNEML_ROBOT_NS=robot_01`),
`ROS_DOMAIN_ID = 42` (§17.2).

| Topic | Tip | Hız | QoS (§17.2) |
|---|---|---|---|
| `/<ns>/telemetry/joint` | `neml_msgs/msg/JointTelemetry` | 50 Hz | BEST_EFFORT, VOLATILE, KEEP_LAST(1) |
| `/<ns>/telemetry/motion_health` | `std_msgs/msg/UInt32MultiArray` | 5 Hz | BEST_EFFORT, VOLATILE, KEEP_LAST(1) |
| `/<ns>/cmd/joint` | `sensor_msgs/msg/JointState` | dinleme | RELIABLE, VOLATILE, KEEP_LAST(10) |

**Mesaj tipleri neden bunlar:** `JointTelemetry` `ros2_ws/src/neml_msgs`
paketinde tanımlıdır (başka bir modülün sahipliğinde) ve firmware onu olduğu
gibi yayınlar. Aynı pakette **komut mesajı yoktur**, bu yüzden komutlar her ROS 2
ve micro-ROS kurulumunda hazır bulunan `sensor_msgs/msg/JointState` ile gelir —
kimsenin yeni bir mesaj eklemesini beklemeye gerek kalmaz.

**Dinamik dizi ≠ tahsis.** `JointTelemetry` sınırsız dizilerden oluşur, ama her
dizi `ros_messages_init()` içinde **statik** bir tampona bağlanır ve kapasitesi
16 olarak yazılır. micro-ROS ancak gelen mesaj kapasiteye sığmazsa ayırıcıyı
çağırır; heap mühürlü olduğu için bu "mesaj düşer" demektir, "malloc" değil.

**Komut doğrulaması (`cmd_callback`):** `position` dizisi tam 16 uzunlukta
olmalıdır. `name` dizisi doluysa, `controllers.yaml` sırasıyla **birebir**
eşleşmelidir (`fl_hip_yaw … rr_ankle`). Eşleşmezse komut sessizce düşürülür;
eski komut 100 ms'de eskir ve eklemler güvenli duruma geçer. Yanlış sıralı bir
dizi kabul etmek, 16 eklemi 16 yanlış açıya sürmek demektir.

**`telemetry/joint` neden 50 Hz:** bir mesaj ≈ 950 bayt (16 isim + 5 × 16
float64). Ajan bağlantısı 921600 baud 8N1 ≈ 92 kB/s; 100 Hz ≈ 95 kB/s ederdi ve
seri taşıma paket düşürmeye başlardı. 50 Hz bağlantının yarısını kullanır.
**Kontrol döngüsü yine 1 kHz'dir** — bu yalnızca dışarının bakma sıklığıdır.

`telemetry/motion_health` üç adet `uint32` taşır (neml_msgs'te bunu taşıyacak
mesaj yok):

| İndeks | İçerik |
|---|---|
| `[0]` | `faults` bit maskesi (`control.h` içindeki `CTRL_FAULT_*`) |
| `[1]` | Açılıştan beri tik aşımı sayısı |
| `[2]` | Açılıştan beri görülen en kötü 1 ms tiki, mikrosaniye (`loop_max_us`) |

Zaman damgası: `rmw_uros_sync_session()` ile ajandan alınır (10 s'de bir
yenilenir). Senkron olmadan önce damga açılıştan beri geçen süredir — dürüst ve
monotondur, Pi tarafında epoch'tan ayırt edilir.

---

## 6. Derleme

### Host testleri (donanım gerekmez, CI'da koşar)

```bash
cd firmware/stm32_motion
cmake -B build-test -DHOST_TESTS=ON
cmake --build build-test
ctest --test-dir build-test --output-on-failure
```

Kapsam: tork/hız kırpma, komut zaman aşımı, e-stop ve aşırı sıcaklık mandalı,
servo paket çerçevelemesi ve sağlama toplamı, birim dönüşümleri.

### Firmware

Gerekenler: `arm-none-eabi-gcc`, CMake ≥ 3.20, STM32CubeF4 kopyası ve önceden
derlenmiş micro-ROS statik kütüphanesi.

```bash
# micro-ROS statik kütüphanesi (bir kez, ROS 2 Jazzy ortamında):
ros2 run micro_ros_setup create_firmware_ws.sh generate_libmicroros
# ÖNEMLİ: neml_msgs, kütüphane üretilmeden ÖNCE mcu_ws'e kopyalanmalıdır,
# yoksa JointTelemetry tip desteği libmicroros içinde bulunmaz:
cp -r ros2_ws/src/neml_msgs firmware/mcu_ws/ros2/
# (sensor_msgs ve std_msgs zaten varsayılan pakette gelir)
ros2 run micro_ros_setup build_firmware.sh
# çıktı: firmware/build/libmicroros.a + include/   (ayrı bir dizine kopyalayın)

cmake -B build \
  -DSTM32CUBEF4_DIR=$HOME/STM32CubeF4 \
  -DMICROROS_DIR=$HOME/microros_static \
  -DNEML_ROBOT_NS=robot_01
cmake --build build
```

> `libmicroros.a` **aynı** derleyici bayraklarıyla üretilmelidir:
> `-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard`. Aksi halde link
> aşamasında ABI uyuşmazlığı alırsınız.

---

## 7. Flash — **YALNIZCA İNSAN**

> `NEML_SPEC.md` §5.4 `global_forbidden`: **`firmware.flash`**. Hiçbir agent,
> hiçbir otonomi döngüsü, hiçbir MCP sunucusu flash çalıştıramaz. Bu bir insan
> eylemidir, CLI ile yapılır ve §5.2 Seviye 4 (MANUFACTURE) onayı gerektirir;
> Seviye 4 onayını **yalnızca `owner`** verebilir.

```bash
# 1. Motor barasını ayır, bataryayı çıkar.
cmake --build build --target flash     # openocd + ST-LINK
# 2. Ardından:
#    - firmware/safety_watchdog/docs/T-071_test_plani.md (Adım 1 ve 3) tekrar koşulur
#    - §8'deki doğrulama tablosu tamamlanır
#    - sonuç safety_checks tablosuna yazılır
```

Kontrolcü firmware'i değiştiyse kalp atışı periyodu yeniden ölçülür (T-071
Adım 1). Bu bir formalite değil: watchdog marjı doğrudan bu periyoda bağlıdır.

---

## 8. Doğrulama (T-072 kabul kriteri)

| Ne | Nasıl | Kabul |
|---|---|---|
| Derleme zamanı tork limiti | `grep MAX_TORQUE_NM ../neml_limits.h` + `_Static_assert`'ler | `2.5f`, derleme geçiyor |
| Limit uygulaması | `ctest --test-dir build-test` | Tüm iddialar geçiyor |
| 1 kHz döngü | `PA5` kalp atışını osiloskopla ölç: 50 ms periyot = 50 tik | 50 ms ± %1 |
| 1 kHz döngü (2. yöntem) | `ros2 topic echo /robot_01/telemetry/motion_health` | `data[2]` (`loop_max_us`) < 800, `data[1]` = 0 |
| micro-ROS görünürlüğü | `ros2 topic hz /robot_01/telemetry/joint` | ~50 Hz (bkz. §5 bağlantı bütçesi) |
| Komut yolu | `ros2 topic pub /robot_01/cmd/joint sensor_msgs/msg/JointState ...` | Eklem hareket ediyor, tork limiti aşılmıyor |
| Yanlış isimli komut reddi | Aynı komutu `name` sırası bozulmuş yayınla | Hareket yok, 100 ms sonra `NO_COMMAND` |
| Aşırı komut reddi | Hız 99 rad/s yayınla | `faults` içinde `VEL_CLAMPED`, hareket 6 rad/s'yi geçmiyor |

**Bilinen tavan (kasıtlı):** 16 eklem tek 1 Mbps servo zincirindedir. 120 baytlık
sync-write 1.2 ms hat süresi tutar; hedef güncellemesi ~400 Hz, bir eklemin geri
bildirimi ~25 ms'de bir gelir. Bu hattın sınırıdır, CPU'nun değil. Yükseltme
yolu: zinciri ikiye böl (iki UART, 8'er eklem — her şey ikiye katlanır) veya
servo firmware'i güvenilir destekliyorsa sync-read (0x82) kullan.
