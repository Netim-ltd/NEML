// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// NEML esp32_aux - ESP32-S3, micro-ROS, 10 Hz telemetry.
// NEML_SPEC.md 2 (MCU yardimci), 13.3 (sensors, limits), 16/T-073, 17.2.
//
// Battery voltage and current, rail current, temperatures and low rate I/O, all
// published once every 100 ms on best effort topics (SPEC 17.2).
//
// This MCU has no authority. It reports; it never actuates and it cannot cut
// power. L0 is the ATmega328P watchdog plus the hardware current comparator
// (SPEC 5.1), both independent of every line below.
//
// TOPICS
//   telemetry/battery   neml_msgs/msg/BatteryState        10 Hz  (T-073)
//   telemetry/aux       std_msgs/msg/Float32MultiArray    10 Hz  (T-073)
//   telemetry/estop     std_msgs/msg/Bool                100 Hz
//
// The e-stop line runs at 100 Hz on purpose and is not part of the T-073 budget:
// ros2_ws/src/neml_safety spends 10 ms of its 50 ms T-074 budget waiting for
// this publisher. Everything else is 10 Hz, which is what T-073 asks for.

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/temperature_sensor.h"
#include "driver/uart.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <rcl/rcl.h>
#include <rclc/rclc.h>
#include <rmw_microros/rmw_microros.h>
#include <uxr/client/transport.h>

#include "esp32_serial_transport.h"

#include <neml_msgs/msg/battery_state.h>
#include <std_msgs/msg/bool.h>
#include <std_msgs/msg/float32_multi_array.h>

#include "sensors.h"

#ifndef NEML_ROBOT_NS
#define NEML_ROBOT_NS "robot_01"
#endif

#define NEML_ROS_DOMAIN_ID 42u          // SPEC 17.2
#define ESTOP_PERIOD_MS 10u             // 100 Hz, feeds the T-074 budget
#define TELEMETRY_EVERY 10u             // every 10th tick -> 10 Hz (SPEC 16/T-073)
// Agent clock sync. The call blocks this task, and this task also carries the
// 100 Hz e-stop line, so the timeout stays at one tick: worst case one e-stop
// sample lands a tick late, once a minute.
#define TIME_SYNC_PERIOD_MS 60000u
#define TIME_SYNC_TIMEOUT_MS 10
#define AUX_TEMP_COUNT 3                // 2 NTC + the ESP32-S3 internal sensor

// I2C: both INA226 sit on one bus.
#define I2C_SDA_IO 8
#define I2C_SCL_IO 9
#define I2C_HZ 400000
#define INA226_ADDR_BATTERY 0x40   // battery pack rail: voltage and body current
#define INA226_ADDR_RAIL5V  0x41   // 5 V buck output (SPEC 13.3 power.rails)

#define INA226_REG_CONFIG 0x00
#define INA226_REG_BUS    0x02
#define INA226_REG_CURRENT 0x04
#define INA226_REG_CAL    0x05
// AVG = 16 samples, 1.1 ms bus and shunt conversion, continuous. One full
// measurement takes 16 * 2.2 ms = 35 ms, comfortably inside the 100 ms period.
#define INA226_CONFIG_VALUE 0x4927

// NTC dividers on ADC1. On the ESP32-S3 ADC1 channel n is GPIO(n+1), so these
// two are GPIO4 and GPIO5 - which is why the digital inputs below start at 15.
#define NTC0_CHANNEL ADC_CHANNEL_3   // GPIO4, motor bay
#define NTC1_CHANNEL ADC_CHANNEL_4   // GPIO5, electronics bay

// Low rate digital inputs. All pulled up here, so a disconnected wire reads as
// the safe interpretation of that line.
#define IO_ESTOP_SENSE_GPIO 15    // NC loop, closed = low
#define IO_CHARGER_GPIO     16
#define IO_WD_ARMED_GPIO    17    // ATmega328P PB1, observation only
#define IO_BMS_FAULT_GPIO   18    // BMS open collector fault output, LOW = fault
#define IO_BIT_ESTOP     0x01u
#define IO_BIT_CHARGER   0x02u
#define IO_BIT_WD_ARMED  0x04u
#define IO_BIT_BMS_FAULT 0x08u

static const char *TAG = "esp32_aux";

static i2c_master_dev_handle_t s_ina_batt;
static i2c_master_dev_handle_t s_ina_rail;
static adc_oneshot_unit_handle_t s_adc;
static adc_cali_handle_t s_adc_cali;
static temperature_sensor_handle_t s_tsens;
static float s_current_lsb_a;

// ---------------------------------------------------------------------------
// INA226
// ---------------------------------------------------------------------------
static esp_err_t ina_write(i2c_master_dev_handle_t dev, uint8_t reg, uint16_t val)
{
    const uint8_t tx[3] = {reg, (uint8_t)(val >> 8), (uint8_t)(val & 0xFFu)};
    return i2c_master_transmit(dev, tx, sizeof(tx), 100);
}

static esp_err_t ina_read(i2c_master_dev_handle_t dev, uint8_t reg, uint16_t *out)
{
    uint8_t rx[2];
    const esp_err_t err = i2c_master_transmit_receive(dev, &reg, 1, rx, sizeof(rx), 100);
    if (err == ESP_OK) {
        *out = (uint16_t)(((uint16_t)rx[0] << 8) | rx[1]);
    }
    return err;
}

static esp_err_t ina_init(i2c_master_bus_handle_t bus, uint8_t addr,
                          i2c_master_dev_handle_t *out)
{
    const i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address  = addr,
        .scl_speed_hz    = I2C_HZ,
    };
    esp_err_t err = i2c_master_bus_add_device(bus, &cfg, out);
    if (err != ESP_OK) {
        return err;
    }
    err = ina_write(*out, INA226_REG_CONFIG, INA226_CONFIG_VALUE);
    if (err != ESP_OK) {
        return err;
    }
    return ina_write(*out, INA226_REG_CAL,
                     ina226_calibration(INA226_SHUNT_OHM, INA226_MAX_CURRENT_A));
}

// ---------------------------------------------------------------------------
// Sampling
// ---------------------------------------------------------------------------
static float read_ntc(adc_channel_t channel)
{
    int raw = 0;
    int mv = 0;
    if (adc_oneshot_read(s_adc, channel, &raw) != ESP_OK ||
        adc_cali_raw_to_voltage(s_adc_cali, raw, &mv) != ESP_OK) {
        return NAN;
    }
    const float r = ntc_resistance((float)mv / 1000.0f, NTC_VREF_V, NTC_SERIES_OHM);
    return ntc_celsius(r, NTC_R0_OHM, NTC_T0_C, NTC_BETA_K);
}

// The e-stop loop is normally closed and pulled up here, so an open loop
// (pressed button, cut wire) reads high. Sampled on its own at 100 Hz.
static bool read_estop(void)
{
    return gpio_get_level(IO_ESTOP_SENSE_GPIO) != 0;
}

static uint32_t read_io(void)
{
    uint32_t io = 0u;
    if (read_estop()) {
        io |= IO_BIT_ESTOP;
    }
    if (gpio_get_level(IO_CHARGER_GPIO)) {
        io |= IO_BIT_CHARGER;
    }
    if (gpio_get_level(IO_WD_ARMED_GPIO)) {
        io |= IO_BIT_WD_ARMED;
    }
    if (!gpio_get_level(IO_BMS_FAULT_GPIO)) {
        io |= IO_BIT_BMS_FAULT;   // open collector: LOW means the BMS tripped
    }
    return io;
}

typedef struct {
    float    battery_v;
    float    battery_current_a;
    float    rail5v_current_a;
    float    temperature_c[AUX_TEMP_COUNT];   // [0] motor bay NTC, [1] electronics NTC, [2] die
    uint32_t io_state;
    uint8_t  faults;
} aux_sample_t;

static void sample(aux_sample_t *s)
{
    uint8_t faults = 0u;
    uint16_t raw = 0u;

    if (ina_read(s_ina_batt, INA226_REG_BUS, &raw) == ESP_OK) {
        s->battery_v = ina226_bus_volts(raw);
    } else {
        s->battery_v = NAN;
        faults |= AUX_FAULT_SENSOR;
    }
    if (ina_read(s_ina_batt, INA226_REG_CURRENT, &raw) == ESP_OK) {
        s->battery_current_a = ina226_amps((int16_t)raw, s_current_lsb_a);
    } else {
        s->battery_current_a = NAN;
        faults |= AUX_FAULT_SENSOR;
    }
    if (ina_read(s_ina_rail, INA226_REG_CURRENT, &raw) == ESP_OK) {
        s->rail5v_current_a = ina226_amps((int16_t)raw, s_current_lsb_a);
    } else {
        s->rail5v_current_a = NAN;
        faults |= AUX_FAULT_SENSOR;
    }

    s->temperature_c[0] = read_ntc(NTC0_CHANNEL);
    s->temperature_c[1] = read_ntc(NTC1_CHANNEL);
    float tsens_c = NAN;
    if (temperature_sensor_get_celsius(s_tsens, &tsens_c) != ESP_OK) {
        tsens_c = NAN;
    }
    s->temperature_c[2] = tsens_c;

    s->io_state = read_io();

    const float body_a = isnan(s->battery_current_a) ? 0.0f : s->battery_current_a;
    s->faults = (uint8_t)(faults | aux_check_limits(body_a, s->temperature_c, AUX_TEMP_COUNT));
}

// ---------------------------------------------------------------------------
// Bring-up
// ---------------------------------------------------------------------------
static void hardware_init(void)
{
    const i2c_master_bus_config_t bus_cfg = {
        .i2c_port                     = I2C_NUM_0,
        .sda_io_num                   = I2C_SDA_IO,
        .scl_io_num                   = I2C_SCL_IO,
        .clk_source                   = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt            = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));
    ESP_ERROR_CHECK(ina_init(bus, INA226_ADDR_BATTERY, &s_ina_batt));
    ESP_ERROR_CHECK(ina_init(bus, INA226_ADDR_RAIL5V, &s_ina_rail));
    s_current_lsb_a = ina226_current_lsb_a(INA226_MAX_CURRENT_A);

    const adc_oneshot_unit_init_cfg_t adc_cfg = {.unit_id = ADC_UNIT_1};
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&adc_cfg, &s_adc));
    const adc_oneshot_chan_cfg_t chan_cfg = {
        .atten    = ADC_ATTEN_DB_12,      // full 0 - 3.1 V span of the divider
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(s_adc, NTC0_CHANNEL, &chan_cfg));
    ESP_ERROR_CHECK(adc_oneshot_config_channel(s_adc, NTC1_CHANNEL, &chan_cfg));

    const adc_cali_curve_fitting_config_t cali_cfg = {
        .unit_id  = ADC_UNIT_1,
        .atten    = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    ESP_ERROR_CHECK(adc_cali_create_scheme_curve_fitting(&cali_cfg, &s_adc_cali));

    temperature_sensor_config_t tsens_cfg = TEMPERATURE_SENSOR_CONFIG_DEFAULT(-10, 80);
    ESP_ERROR_CHECK(temperature_sensor_install(&tsens_cfg, &s_tsens));
    ESP_ERROR_CHECK(temperature_sensor_enable(s_tsens));

    const gpio_config_t in_cfg = {
        .pin_bit_mask = (1ULL << IO_ESTOP_SENSE_GPIO) | (1ULL << IO_CHARGER_GPIO) |
                        (1ULL << IO_WD_ARMED_GPIO) | (1ULL << IO_BMS_FAULT_GPIO),
        .mode         = GPIO_MODE_INPUT,
        .pull_up_en   = GPIO_PULLUP_ENABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&in_cfg));
}

// ---------------------------------------------------------------------------
// micro-ROS messages
//
// neml_msgs (ros2_ws/src/neml_msgs, owned elsewhere) defines BatteryState, so
// the pack goes out in that. It defines nothing for rail current, bay
// temperatures and digital inputs.
//
// ponytail: those four numbers and two bitmasks ride in one
// std_msgs/Float32MultiArray with the index table below, because inventing a
// message means waiting for another package to grow one. Upgrade path: when
// neml_msgs gains an AuxTelemetry, swap the type here and delete the table.
//   [0] motor bay NTC, C        [3] 5 V rail current, A
//   [1] electronics bay NTC, C  [4] io bitmask  (IO_BIT_*)
//   [2] ESP32-S3 die, C         [5] fault bitmask (AUX_FAULT_*)
// ---------------------------------------------------------------------------
#define AUX_ARRAY_LEN 6

static neml_msgs__msg__BatteryState   s_batt_msg;
static std_msgs__msg__Float32MultiArray s_aux_msg;
static std_msgs__msg__Bool            s_estop_msg;
static float s_aux_data[AUX_ARRAY_LEN];
static char  s_batt_frame[16];

static void messages_init(void)
{
    // Static buffers, set up once: the sequences below never touch the heap.
    s_batt_msg.header.frame_id.data     = s_batt_frame;
    s_batt_msg.header.frame_id.capacity = sizeof(s_batt_frame);
    strncpy(s_batt_frame, "battery_link", sizeof(s_batt_frame) - 1u);
    s_batt_frame[sizeof(s_batt_frame) - 1u] = '\0';
    s_batt_msg.header.frame_id.size     = strlen(s_batt_frame);

    // SPEC 13.3 power.battery: 4 cells, 5200 mAh.
    s_batt_msg.cell_count = LIPO_CELLS;
    s_batt_msg.capacity_ah = LIPO_CAPACITY_AH;
    // No balance-lead taps are wired to this board, so there are no per cell
    // voltages to report. An empty sequence says that; four copies of
    // voltage/4 would be a fabricated measurement in a field an operator reads
    // as measured.
    s_batt_msg.cell_voltage_v.data     = NULL;
    s_batt_msg.cell_voltage_v.size     = 0u;
    s_batt_msg.cell_voltage_v.capacity = 0u;

    s_aux_msg.data.data     = s_aux_data;
    s_aux_msg.data.size     = AUX_ARRAY_LEN;
    s_aux_msg.data.capacity = AUX_ARRAY_LEN;
}

// Absolute time comes from the agent. Before the first sync, stamps are time
// since boot: monotonic and obviously not an epoch.
static builtin_interfaces__msg__Time ros_stamp(void)
{
    builtin_interfaces__msg__Time t;
    if (rmw_uros_epoch_synchronized()) {
        const int64_t ns = rmw_uros_epoch_nanos();
        t.sec     = (int32_t)(ns / 1000000000LL);
        t.nanosec = (uint32_t)(ns % 1000000000LL);
    } else {
        const int64_t us = esp_timer_get_time();
        t.sec     = (int32_t)(us / 1000000LL);
        t.nanosec = (uint32_t)((us % 1000000LL) * 1000LL);
    }
    return t;
}

static void fill_battery(const aux_sample_t *s)
{
    s_batt_msg.header.stamp = ros_stamp();
    s_batt_msg.voltage_v    = s->battery_v;
    s_batt_msg.current_a    = s->battery_current_a;
    s_batt_msg.percentage   = lipo_soc(s->battery_v);
    // Derived, not counted: see lipo_soc() in sensors.h for what that is worth.
    s_batt_msg.charge_ah    = LIPO_CAPACITY_AH * s_batt_msg.percentage;
    s_batt_msg.temperature_c = s->temperature_c[0];   // pack NTC
    s_batt_msg.bms_ok       = (s->io_state & IO_BIT_BMS_FAULT) == 0u;
}

static void telemetry_task(void *arg)
{
    (void)arg;

    static const uart_port_t uart_port = UART_NUM_1;
    rmw_uros_set_custom_transport(true, (void *)&uart_port, esp32_serial_open,
                                  esp32_serial_close, esp32_serial_write,
                                  esp32_serial_read);

    rcl_allocator_t allocator = rcl_get_default_allocator();
    rclc_support_t  support;
    rcl_node_t      node;
    rcl_publisher_t pub_batt;
    rcl_publisher_t pub_aux;
    rcl_publisher_t pub_estop;

    // The agent may not be up yet; wait for it rather than failing the boot.
    while (rmw_uros_ping_agent(1000, 1) != RMW_RET_OK) {
        ESP_LOGW(TAG, "micro-ROS agent not reachable, retrying");
    }

    // SPEC 17.2 telemetry class, exactly: BEST_EFFORT / VOLATILE / KEEP_LAST(1).
    // rmw_qos_profile_sensor_data is the first two but keeps 5, so fix the depth.
    rmw_qos_profile_t telemetry_qos = rmw_qos_profile_sensor_data;
    telemetry_qos.depth = 1;

    rcl_init_options_t init_options = rcl_get_zero_initialized_init_options();
    if (rcl_init_options_init(&init_options, allocator) != RCL_RET_OK ||
        rcl_init_options_set_domain_id(&init_options, NEML_ROS_DOMAIN_ID) != RCL_RET_OK ||
        rclc_support_init_with_options(&support, 0, NULL, &init_options, &allocator) !=
            RCL_RET_OK ||
        rclc_node_init_default(&node, "esp32_aux", NEML_ROBOT_NS, &support) != RCL_RET_OK ||
        rclc_publisher_init(
            &pub_batt, &node, ROSIDL_GET_MSG_TYPE_SUPPORT(neml_msgs, msg, BatteryState),
            "telemetry/battery", &telemetry_qos) != RCL_RET_OK ||
        rclc_publisher_init(
            &pub_aux, &node, ROSIDL_GET_MSG_TYPE_SUPPORT(std_msgs, msg, Float32MultiArray),
            "telemetry/aux", &telemetry_qos) != RCL_RET_OK ||
        rclc_publisher_init(
            &pub_estop, &node, ROSIDL_GET_MSG_TYPE_SUPPORT(std_msgs, msg, Bool),
            "telemetry/estop", &telemetry_qos) != RCL_RET_OK) {
        ESP_LOGE(TAG, "micro-ROS init failed, restarting");
        esp_restart();
    }

    messages_init();
    (void)rmw_uros_sync_session(1000);

    aux_sample_t s = {0};
    unsigned consecutive_failures = 0u;
    unsigned ticks = 0u;
    int64_t next_sync_us = esp_timer_get_time() + (int64_t)TIME_SYNC_PERIOD_MS * 1000;
    TickType_t next = xTaskGetTickCount();

    for (;;) {
        vTaskDelayUntil(&next, pdMS_TO_TICKS(ESTOP_PERIOD_MS));

        // 100 Hz: the e-stop line, on its own, first. neml_safety budgets 10 ms
        // for this sample in its 50 ms T-074 chain, so it does not wait behind
        // an I2C conversion.
        s_estop_msg.data = read_estop();
        const bool estop_ok = rcl_publish(&pub_estop, &s_estop_msg, NULL) == RCL_RET_OK;

        if (++ticks % TELEMETRY_EVERY != 0u) {
            continue;
        }

        // 10 Hz: everything else (SPEC 16/T-073).
        sample(&s);
        fill_battery(&s);
        s_aux_data[0] = s.temperature_c[0];
        s_aux_data[1] = s.temperature_c[1];
        s_aux_data[2] = s.temperature_c[2];
        s_aux_data[3] = s.rail5v_current_a;
        s_aux_data[4] = (float)s.io_state;
        s_aux_data[5] = (float)s.faults;

        if (s.faults & AUX_FAULT_OVER_CURRENT) {
            ESP_LOGW(TAG, "body current over the SPEC 13.3 limit: %.2f A",
                     (double)s.battery_current_a);
        }
        if (s.faults & AUX_FAULT_OVER_TEMP) {
            ESP_LOGW(TAG, "temperature over the SPEC 13.3 limit");
        }

        const bool published = (rcl_publish(&pub_batt, &s_batt_msg, NULL) == RCL_RET_OK) &&
                               (rcl_publish(&pub_aux, &s_aux_msg, NULL) == RCL_RET_OK) &&
                               estop_ok;
        if (published) {
            consecutive_failures = 0u;
        } else if (++consecutive_failures > 50u) {
            // ponytail: the link is gone and rebuilding an XRCE session in place
            // is fiddly. Rebooting costs about a second of telemetry on an MCU
            // that holds no state worth keeping, and it always works. Move to a
            // proper reconnect only if that second ever matters.
            ESP_LOGE(TAG, "agent lost for 5 s, restarting");
            esp_restart();
        }

        if (esp_timer_get_time() >= next_sync_us) {
            next_sync_us = esp_timer_get_time() + (int64_t)TIME_SYNC_PERIOD_MS * 1000;
            (void)rmw_uros_sync_session(TIME_SYNC_TIMEOUT_MS);
        }
    }
}

void app_main(void)
{
    hardware_init();
    // 16 KB: rcl plus the publish path. micro-ROS is not frugal with stack.
    xTaskCreate(telemetry_task, "aux_telemetry", 16 * 1024, NULL, 5, NULL);
}
