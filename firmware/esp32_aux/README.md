<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# esp32_aux — yardımcı telemetri MCU'su (ESP32-S3 + micro-ROS)

**Sürüm:** v1.1.0 (`NEML_SPEC.md` §13.3 `electronics.aux_mcu.firmware`)
**Kontrat:** §2 (MCU yardımcı), §13.3 (sensörler, limitler), §16 T-073, §17.2 (ROS/QoS)

Batarya, akım (ina226 × 2), sıcaklıklar ve düşük hızlı G/Ç. Telemetri **10 Hz**,
ROS 2'de görünür (T-073 kabul kriteri).

> **Bu MCU'nun yetkisi yoktur.** Raporlar; hiçbir şeyi sürmez, gücü kesemez.
> L0 = ATmega328P watchdog + donanımsal akım komparatörü (§5.1) ve ikisi de
> buradaki hiçbir satıra bağlı değildir. `aux_check_limits()` bir **rapor**
> üretir, bir koruma değil.

---

## 1. Topic'ler

Namespace derleme zamanında verilir (`-DNEML_ROBOT_NS=robot_01`),
`ROS_DOMAIN_ID = 42` (§17.2). Üçü de telemetri sınıfıdır:
**BEST_EFFORT / VOLATILE / KEEP_LAST(1)**.

| Topic | Tip | Hız |
|---|---|---|
| `/<ns>/telemetry/battery` | `neml_msgs/msg/BatteryState` | 10 Hz |
| `/<ns>/telemetry/aux` | `std_msgs/msg/Float32MultiArray` | 10 Hz |
| `/<ns>/telemetry/estop` | `std_msgs/msg/Bool` | **100 Hz** |

**E-stop neden 100 Hz:** `ros2_ws/src/neml_safety` T-074 bütçesinde
(“e-stop olayı < 50 ms'de tüm yığına yayılıyor”) bu yayıncı için **10 ms**
ayırır. T-073'ün istediği 10 Hz diğer iki topic içindir; e-stop hattı o bütçeye
dahil değildir ve döngünün en başında, I2C dönüşümünü beklemeden yayınlanır.

**`telemetry/aux` indeks tablosu** (neml_msgs'te bunu taşıyacak mesaj yok):

| İndeks | İçerik |
|---|---|
| `[0]` | Motor bölmesi NTC, °C |
| `[1]` | Elektronik bölmesi NTC, °C |
| `[2]` | ESP32-S3 dahili sıcaklık sensörü, °C |
| `[3]` | 5 V rayı akımı, A (§13.3 `power.rails`) |
| `[4]` | G/Ç bit maskesi — `IO_BIT_ESTOP` 0x01, `IO_BIT_CHARGER` 0x02, `IO_BIT_WD_ARMED` 0x04, `IO_BIT_BMS_FAULT` 0x08 |
| `[5]` | Arıza bit maskesi — `AUX_FAULT_OVER_CURRENT` 0x01, `AUX_FAULT_OVER_TEMP` 0x02, `AUX_FAULT_SENSOR` 0x04 |

`BatteryState.cell_voltage_v` **boş yayınlanır**: bu karta denge (balance)
uçları bağlı değildir, hücre gerilimi ölçülmez. `voltage_v / 4` yazmak,
operatörün "ölçülmüş" diye okuyacağı bir alana uydurma veri koymak olurdu.

---

## 2. Pin bağlantıları

| Pin | Yön | İşlev |
|---|---|---|
| `GPIO8` / `GPIO9` | I2C | SDA / SCL, 400 kHz. INA226 ×2: `0x40` batarya rayı, `0x41` 5 V rayı |
| `GPIO4` (ADC1_CH3) | analog | Motor bölmesi NTC böleni |
| `GPIO5` (ADC1_CH4) | analog | Elektronik bölmesi NTC böleni |
| `GPIO15` | giriş | E-stop algılama (NC halka, pull-up: **açık halka = HIGH**) |
| `GPIO16` | giriş | Şarj cihazı bağlı sinyali |
| `GPIO17` | giriş | ATmega328P `PB1` — watchdog "armed" durumu, **yalnızca gözlem** |
| `GPIO18` | giriş | BMS arıza çıkışı (açık kollektör, **LOW = arıza**) |
| `UART1` | TX/RX | micro-ROS ajanı (Raspberry Pi 5). `UART0` log içindir, karıştırmayın |

> ESP32-S3'te ADC1 kanal *n* = GPIO(*n*+1); bu yüzden dijital girişler 15'ten
> başlar, aksi halde NTC kanallarıyla çakışırlardı. Strapping pinleri (0, 3, 45,
> 46) ve USB (19, 20) kullanılmaz. **Kartı bağlamadan önce `main/main.c`
> başındaki pin tanımlarını şemaya karşı doğrulayın.**
>
> Kablolama: BMS arıza çıkışı güç kartındaki `J30`'a, oradan `J31` üzerinden
> ESP32 `GPIO18`'e gider (`hardware/electronics/templates/power_dist_v1.py`,
> `R9` 10 kΩ pull-up). Harness takılı değilse hat yine yüksek okunur.
>
> `GPIO18` pull-up'lıdır: BMS arıza hattı bağlı değilse "arıza yok" okunur.
> Bu alan yalnızca rapordur — gerçek koruma BMS'in kendisi ve donanımsal akım
> komparatörüdür (§5.1).

Shunt: her iki kanalda **2 mΩ** (20 A'da 40 mV, INA226'nın ±81.92 mV aralığında).

---

## 3. Kalibrasyon düğmeleri (fiziksel dünya modele uymaz)

Hepsi `main/sensors.h` içindedir ve **ölçülerek** ayarlanır:

| Sabit | Ne zaman değişir |
|---|---|
| `INA226_SHUNT_OHM` | %1'lik shunt + iz direnci kolayca %3 sapar. Tezgâh beslemesi ile karşılaştırıp düzeltin |
| `NTC_OFFSET_C` | Referans termometreye karşı oda sıcaklığında ve 60 °C'de trimlenir |
| `NTC_BETA_K`, `NTC_R0_OHM` | Farklı bir NTC parçası kullanılırsa |
| `lipo_soc()` eğrisi | Farklı bir hücre kimyası/markası kullanılırsa |

`lipo_soc()` bir **gerilim tablosudur, kulometre değil**: yük altında paketin iç
direnci kadar düşük okur. "Eve dön" kararı için yeterlidir, §13.3
`performance.endurance_min` ölçümü için değildir (yükseltme yolu fonksiyonun
başındaki `ponytail:` notunda).

---

## 4. Derleme

### Host testleri (donanım ve ESP-IDF gerekmez, CI'da koşar)

```bash
cd firmware/esp32_aux
cmake -B build-test -DHOST_TESTS=ON
cmake --build build-test
ctest --test-dir build-test --output-on-failure
```

Kapsam: INA226 ölçekleme ve kalibrasyon kaydı, NTC beta modeli ve açık/kısa
devre tespiti, LiPo şarj durumu eğrisi, §13.3 limit kontrolleri.

### Firmware (ESP-IDF v5.x, Ubuntu 24.04)

```bash
# 1. micro-ROS bileşeni — ağaca kopyalanmaz, yanına klonlanır (§1.3)
cd firmware/esp32_aux
git clone -b jazzy https://github.com/micro-ROS/micro_ros_espidf_component.git \
    components/micro_ros_espidf_component

# 2. Özel mesajlar: neml_msgs bileşenin extra_packages'ına girmeli, yoksa
#    BatteryState tip desteği libmicroros içinde bulunmaz
cp -r ../../ros2_ws/src/neml_msgs \
    components/micro_ros_espidf_component/extra_packages/

# 3. Derle
. $IDF_PATH/export.sh
idf.py set-target esp32s3
idf.py build
```

Ajan tarafında (Pi 5):

```bash
ros2 run micro_ros_agent micro_ros_agent serial --dev /dev/ttyAUX -b 115200
```

---

## 5. Flash — **YALNIZCA İNSAN**

> `NEML_SPEC.md` §5.4 `global_forbidden`: **`firmware.flash`**. Hiçbir agent,
> hiçbir otonomi döngüsü, hiçbir MCP sunucusu flash çalıştıramaz. Flash bir
> **insan eylemidir**, elle, CLI ile yapılır ve §5.2 Seviye 4 (MANUFACTURE)
> onayı gerektirir; Seviye 4 onayını **yalnızca `owner`** verebilir.

```bash
# Batarya çıkarılı, kart USB'den beslenirken:
idf.py -p /dev/ttyUSB0 flash monitor
```

---

## 6. Doğrulama (T-073 kabul kriteri)

| Ne | Nasıl | Kabul |
|---|---|---|
| Aritmetik | `ctest --test-dir build-test` | Tüm iddialar geçiyor |
| ROS 2 görünürlüğü | `ros2 topic list \| grep telemetry` | Üç topic de listede |
| Telemetri hızı | `ros2 topic hz /robot_01/telemetry/battery` | **10 Hz ± %5** |
| E-stop hızı | `ros2 topic hz /robot_01/telemetry/estop` | ~100 Hz |
| E-stop doğruluğu | Mantar butona bas | `data: true`, bırakınca `false` (mandal Pi tarafındadır) |
| Batarya gerilimi | Multimetre ile karşılaştır | ± 50 mV |
| Akım | Bilinen yük (ör. 5 A) | ± %3 — sapma varsa `INA226_SHUNT_OHM` |
| Sıcaklık | Referans termometre | ± 2 °C — sapma varsa `NTC_OFFSET_C` |
| Sensör arızası | NTC'yi söküp tak | `[5]` içinde `AUX_FAULT_SENSOR`, sıcaklık `NaN` (uydurma değer yok) |
| Ajan kaybı | Ajanı durdur, 5 s bekle | MCU yeniden başlar ve ajan dönünce yayına devam eder |
