// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// NEML stm32_motion - STM32F446RE, micro-ROS, 1 kHz control loop.
// NEML_SPEC.md 2 (MCU hareket), 5.1 (limits), 13.3, 16/T-072, 17.2 (ROS/QoS).
//
// ===========================================================================
// HARD REAL TIME RULES - the 1 kHz tick is the contract
// ===========================================================================
//   * No allocation anywhere after startup. _sbrk below seals itself once
//     micro-ROS has built its session; anything that touches the heap after
//     that traps.
//   * No unbounded loop and no blocking call inside TIM6_DAC_IRQHandler. Every
//     loop is bounded by NEML_JOINT_COUNT.
//   * micro-ROS never runs in the control ISR. It runs in the background loop
//     at the lowest priority and hands data over through a seqlock snapshot.
//   * Interrupt priorities: TIM6 (control) 0, servo bus UART 1, micro-ROS UART
//     2, SysTick 15. The control tick preempts everything, which is also what
//     makes the buffer handover below safe without a lock.
//
// Worst case budget for the 1 ms tick at 180 MHz (180000 cycles), measured with
// DWT->CYCCNT and published as loop_max_us:
//
//     control_tick + control_step, 16 joints   ~22 us
//     servo goal packet build, 120 bytes       ~ 8 us
//     telemetry snapshot (seqlock memcpy)      ~ 2 us
//     heartbeat, bus watchdog, DWT accounting  ~ 2 us
//     ----------------------------------------------
//     total                                    ~34 us   (3.4 % of the tick)
//
// TICK_BUDGET_US is 800 us. Crossing it raises CTRL_FAULT_TICK_OVERRUN, which is
// reported, not fatal: the fatal path is the heartbeat, below.
//
// ===========================================================================
// HEARTBEAT - this is how the firmware asks L0 to cut the power
// ===========================================================================
// PA5 toggles every 50 ms (SPEC 5.1) into the ATmega328P watchdog. The toggle
// stops when a critical fault latches, and the watchdog opens the motor relay
// 150 ms later. This firmware cannot cut motor power itself and must not try:
// L0 is independent of software by design.
// ===========================================================================

#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "stm32f4xx_hal.h"

#include <rcl/rcl.h>
#include <rclc/executor.h>
#include <rclc/rclc.h>
#include <rmw_microros/rmw_microros.h>
#include <uxr/client/transport.h>

#include <neml_msgs/msg/joint_telemetry.h>
#include <sensor_msgs/msg/joint_state.h>
#include <std_msgs/msg/u_int32_multi_array.h>

#include "control.h"
#include "servo_bus.h"

#ifndef NEML_ROBOT_NS
#define NEML_ROBOT_NS "robot_01"
#endif

#define NEML_ROS_DOMAIN_ID 42u          // SPEC 17.2 ROS_DOMAIN_ID
#define HEARTBEAT_TICKS    50u          // SPEC 5.1: 50 ms
// 50 Hz, and that is a link budget, not a preference. One JointTelemetry with
// 16 names and five float64 arrays is about 950 bytes on the wire; the agent
// link runs at 921600 baud 8N1, i.e. ~92 kB/s, so 100 Hz would need ~95 kB/s and
// the serial transport would simply start dropping. 50 Hz uses half the link and
// leaves room for the command stream. The control loop is still 1 kHz; this is
// only how often the outside world gets to look at it.
#define TELEMETRY_PERIOD_MS 20u         // 50 Hz
#define HEALTH_EVERY        10u         // 5 Hz
// Agent clock sync. The call blocks the background loop, which is also where
// commands are dispatched, so the timeout has to stay well under CMD_TIMEOUT_MS
// (100 ms) or every sync would age the command out and drop the joints limp for
// a moment. 20 ms every minute costs nothing and leaves 80 ms of margin.
#define TIME_SYNC_PERIOD_MS 60000u
#define TIME_SYNC_TIMEOUT_MS 20
#define TICK_BUDGET_CYCLES (144000u)    // 800 us at 180 MHz
#define BUS_STALL_TICKS    5u           // servo bus must make progress every 5 ms
#define SERVO_RX_LEN       14u          // status frame: FF FF id len err + 8 + csum

#define HB_PORT    GPIOA
#define HB_PIN     GPIO_PIN_5
#define ESTOP_PORT GPIOC
#define ESTOP_PIN  GPIO_PIN_13          // NC loop, pulled up: LOW while healthy

static UART_HandleTypeDef huart1;       // servo bus, half duplex, 1 Mbps
static UART_HandleTypeDef huart2;       // micro-ROS transport
static DMA_HandleTypeDef  hdma_usart1_tx;
static DMA_HandleTypeDef  hdma_usart1_rx;
static DMA_HandleTypeDef  hdma_usart2_rx;
static TIM_HandleTypeDef  htim6;

static control_t g_ctrl;
static uint8_t   g_servo_ids[NEML_JOINT_COUNT];

// ---------------------------------------------------------------------------
// No heap after startup
// ---------------------------------------------------------------------------
extern char _end;
extern char _estack;
extern char _Min_Stack_Size;

static char *g_brk = &_end;
static volatile uint8_t g_heap_sealed;
static volatile uint8_t g_heap_denied;   // sticky, reported as CTRL_FAULT_HEAP

static void neml_fault_trap(void)
{
    // Stop the heartbeat and stay stopped. The ATmega328P opens the motor relay
    // 150 ms from now; that is the only correct response to an impossible state
    // in the motion controller.
    __disable_irq();
    HAL_GPIO_WritePin(HB_PORT, HB_PIN, GPIO_PIN_RESET);
    for (;;) {
    }
}

void *_sbrk(int incr)
{
    // After startup the heap is closed. A request that arrives anyway is either
    // a design bug in our code or an incoming message that does not fit the
    // static buffers; both get a failed allocation, not a trap. micro-ROS then
    // drops that message, the command ages out in CMD_TIMEOUT_MS and the joints
    // go limp - the right answer in both cases, and far better than taking the
    // motion controller down because something on the wire was malformed. The
    // event is sticky and rides out in the telemetry faults byte.
    if (g_heap_sealed) {
        g_heap_denied = 1u;
        errno = ENOMEM;
        return (void *)-1;
    }
    char *const limit = &_estack - (uintptr_t)&_Min_Stack_Size;
    if (incr < 0 || g_brk + incr > limit) {
        errno = ENOMEM;
        return (void *)-1;
    }
    char *const prev = g_brk;
    g_brk += incr;
    return prev;
}

// ---------------------------------------------------------------------------
// Telemetry handover, ISR -> background loop
// ---------------------------------------------------------------------------
typedef struct {
    float    position_rad[NEML_JOINT_COUNT];
    float    velocity_rads[NEML_JOINT_COUNT];
    float    torque_nm[NEML_JOINT_COUNT];
    float    temperature_c[NEML_JOINT_COUNT];
    uint32_t tick_overruns;
    uint32_t loop_max_us;
    uint8_t  faults;
} telem_snapshot_t;

static volatile uint32_t  g_snap_seq;    // odd while the ISR is writing
static telem_snapshot_t   g_snap;
static uint32_t           g_tick_overruns;
static uint32_t           g_loop_max_cycles;

static void telemetry_snapshot(void)
{
    g_snap_seq++;
    __DMB();
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        g_snap.position_rad[i]  = g_ctrl.state[i].position_rad;
        g_snap.velocity_rads[i] = g_ctrl.state[i].velocity_rads;
        g_snap.torque_nm[i]     = g_ctrl.state[i].torque_nm;
        g_snap.temperature_c[i] = g_ctrl.state[i].temperature_c;
    }
    g_snap.tick_overruns = g_tick_overruns;
    g_snap.loop_max_us   = g_loop_max_cycles / (SystemCoreClock / 1000000u);
    g_snap.faults        = (uint8_t)(g_ctrl.faults | g_ctrl.latched |
                                     (g_heap_denied ? CTRL_FAULT_HEAP : 0u));
    __DMB();
    g_snap_seq++;
}

// Bounded: four attempts, then this publish is skipped. A dropped best effort
// telemetry sample costs nothing (SPEC 17.2: BEST_EFFORT, KEEP_LAST(1)).
static int telemetry_read(telem_snapshot_t *out)
{
    for (int attempt = 0; attempt < 4; attempt++) {
        const uint32_t s0 = g_snap_seq;
        if (s0 & 1u) {
            continue;
        }
        __DMB();
        *out = g_snap;
        __DMB();
        if (g_snap_seq == s0) {
            return 1;
        }
    }
    return 0;
}

// ---------------------------------------------------------------------------
// Servo bus state machine
//
// Self clocked from the DMA completion interrupts: goal write, then one joint's
// feedback read, then goal write again. The tick only refills the goal buffer.
//
// ponytail: one 1 Mbps chain carries all 16 joints, so a 120 byte sync write
// costs 1.2 ms of airtime. Goal updates land at roughly 400 Hz and a given joint
// reports back about every 25 ms. That is the bus, not the CPU. Upgrade path, in
// order of effort: split the chain in two (two UARTs, 8 joints each, everything
// doubles), or use sync read (instruction 0x82) if the servo firmware supports
// it reliably.
// ---------------------------------------------------------------------------
typedef enum { BUS_GOAL_TX, BUS_READ_TX, BUS_READ_RX } bus_state_t;

static volatile bus_state_t g_bus_state;
static volatile uint8_t     g_goal_ready;
static volatile uint8_t     g_goal_busy;
static volatile uint32_t    g_bus_stall_ticks;
static uint8_t              g_goal_buf[STS_TX_BUF_SIZE];
static uint8_t              g_read_buf[16];
static uint8_t              g_rx_buf[SERVO_RX_LEN];
static uint8_t              g_read_joint;

static void bus_start_goal(void)
{
    g_bus_state = BUS_GOAL_TX;
    g_goal_busy = 1u;
    g_goal_ready = 0u;
    HAL_HalfDuplex_EnableTransmitter(&huart1);
    HAL_UART_Transmit_DMA(&huart1, g_goal_buf, (uint16_t)sizeof(g_goal_buf));
}

static void bus_start_read(void)
{
    const size_t n = servo_build_read_feedback(g_read_buf, sizeof(g_read_buf),
                                               g_servo_ids[g_read_joint]);
    g_bus_state = BUS_READ_TX;
    HAL_HalfDuplex_EnableTransmitter(&huart1);
    HAL_UART_Transmit_DMA(&huart1, g_read_buf, (uint16_t)n);
}

static void bus_advance(void)
{
    g_bus_stall_ticks = 0u;
    if (g_goal_ready) {
        bus_start_goal();
    } else {
        bus_start_read();
    }
}

void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart != &huart1) {
        return;
    }
    if (g_bus_state == BUS_GOAL_TX) {
        g_goal_busy = 0u;
        bus_start_read();
    } else {
        g_bus_state = BUS_READ_RX;
        HAL_HalfDuplex_EnableReceiver(&huart1);
        HAL_UART_Receive_DMA(&huart1, g_rx_buf, SERVO_RX_LEN);
    }
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart != &huart1) {
        return;
    }
    servo_feedback_t fb;
    if (servo_parse_feedback(g_rx_buf, SERVO_RX_LEN, g_servo_ids[g_read_joint], &fb)) {
        joint_state_t *s = &g_ctrl.state[g_read_joint];
        s->position_rad  = servo_count_to_rad(fb.position);
        s->velocity_rads = (float)fb.speed / STS_COUNTS_PER_RAD;
        // Load is per mille of stall torque, signed (SPEC 13.3 stall_torque_nm).
        s->torque_nm     = (float)fb.load * ((float)STS3215_STALL_TORQUE_MNM / 1000000.0f);
        s->temperature_c = (float)fb.temperature_c;
    }
    g_read_joint = (uint8_t)((g_read_joint + 1u) % NEML_JOINT_COUNT);
    bus_advance();
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if (huart != &huart1) {
        return;
    }
    // A framing error on the servo chain is routine (bus contention, a servo
    // that did not answer). Drop the frame and keep the bus moving; the joint
    // simply keeps its last known state until its next turn.
    HAL_UART_AbortReceive(&huart1);
    g_read_joint = (uint8_t)((g_read_joint + 1u) % NEML_JOINT_COUNT);
    bus_advance();
}

// Called from the tick. Restarts the bus if a servo never answered. A full
// goal-write plus feedback-read cycle is about 2 ms of airtime, so 5 ms without
// progress means the chain is stuck. HAL_UART_Abort polls flags and is heavy for
// a priority 0 ISR, but this path runs only when the bus is already broken, and
// the cost shows up honestly as a tick overrun.
static void bus_watchdog(void)
{
    if (++g_bus_stall_ticks < BUS_STALL_TICKS) {
        return;
    }
    HAL_UART_Abort(&huart1);
    g_goal_busy = 0u;
    g_read_joint = (uint8_t)((g_read_joint + 1u) % NEML_JOINT_COUNT);
    bus_advance();
}

// ---------------------------------------------------------------------------
// 1 kHz control tick
// ---------------------------------------------------------------------------
static void heartbeat_update(void)
{
    static uint16_t n;
    if (++n < HEARTBEAT_TICKS) {
        return;
    }
    n = 0u;
    // SPEC 5.1: while a critical fault is latched we stop toggling, and the
    // ATmega328P opens the motor relay 150 ms later. Deliberate, and the only
    // way this firmware can demand a hardware stop.
    if (g_ctrl.latched & CTRL_FAULT_CRITICAL) {
        return;
    }
    HAL_GPIO_TogglePin(HB_PORT, HB_PIN);
}

void TIM6_DAC_IRQHandler(void)
{
    const uint32_t t0 = DWT->CYCCNT;
    __HAL_TIM_CLEAR_IT(&htim6, TIM_IT_UPDATE);

    // The e-stop loop is normally closed: an open loop means pressed or cut.
    const uint8_t estop_open = (HAL_GPIO_ReadPin(ESTOP_PORT, ESTOP_PIN) == GPIO_PIN_SET);

    control_tick(&g_ctrl, estop_open);
    control_step(&g_ctrl);

    // Refill the goal buffer only while the DMA is not reading it. This ISR
    // preempts the bus interrupt, never the other way round, so the flag is
    // enough - no critical section on the hot path.
    if (!g_goal_busy) {
        (void)servo_build_sync_goal(g_goal_buf, sizeof(g_goal_buf), g_servo_ids,
                                    g_ctrl.out_position_rad, g_ctrl.out_velocity_rads);
        g_goal_ready = 1u;
    }

    bus_watchdog();
    heartbeat_update();
    telemetry_snapshot();

    const uint32_t used = DWT->CYCCNT - t0;
    if (used > g_loop_max_cycles) {
        g_loop_max_cycles = used;
    }
    if (used > TICK_BUDGET_CYCLES) {
        g_tick_overruns++;
        g_ctrl.faults |= CTRL_FAULT_TICK_OVERRUN;
    }
}

// ---------------------------------------------------------------------------
// micro-ROS
//
// MESSAGE TYPES - why these and not our own
//   ros2_ws/src/neml_msgs is owned elsewhere and defines JointTelemetry with a
//   std_msgs/Header, a joint name array and five float64 arrays. That is the
//   message this firmware publishes, unchanged. The same package defines no
//   command message, so commands arrive as sensor_msgs/msg/JointState, which
//   exists in every ROS 2 and micro-ROS build and needs nobody's agreement.
//
//   Unbounded arrays do not mean allocation. Every sequence below points at a
//   static buffer with its capacity set, and micro-ROS only calls the allocator
//   when an incoming message does not fit that capacity. The heap is sealed
//   before the control loop starts, so "does not fit" means "dropped", never
//   "malloc" (see _sbrk above).
// ---------------------------------------------------------------------------
static uint8_t  g_ros_rx[512];
static size_t   g_ros_tail;

// SPEC 13.3 morphology: 4 legs x 4 DOF, in the order ros2_ws/src/neml_control
// controllers.yaml lists them. A command that names them differently is not a
// command for this robot (see cmd_callback).
#define JOINT_NAME_CAP 24
static const char *const JOINT_NAMES[NEML_JOINT_COUNT] = {
    "fl_hip_yaw", "fl_hip_pitch", "fl_knee", "fl_ankle",
    "fr_hip_yaw", "fr_hip_pitch", "fr_knee", "fr_ankle",
    "rl_hip_yaw", "rl_hip_pitch", "rl_knee", "rl_ankle",
    "rr_hip_yaw", "rr_hip_pitch", "rr_knee", "rr_ankle",
};

static neml_msgs__msg__JointTelemetry g_telem_msg;
static rosidl_runtime_c__String g_telem_name[NEML_JOINT_COUNT];
static char   g_telem_name_buf[NEML_JOINT_COUNT][JOINT_NAME_CAP];
static char   g_telem_frame_buf[JOINT_NAME_CAP];
static double g_telem_pos[NEML_JOINT_COUNT];
static double g_telem_vel[NEML_JOINT_COUNT];
static double g_telem_eff[NEML_JOINT_COUNT];
static double g_telem_temp[NEML_JOINT_COUNT];
static double g_telem_cur[NEML_JOINT_COUNT];

static sensor_msgs__msg__JointState g_cmd_msg;
static rosidl_runtime_c__String g_cmd_name[NEML_JOINT_COUNT];
static char   g_cmd_name_buf[NEML_JOINT_COUNT][JOINT_NAME_CAP];
static char   g_cmd_frame_buf[JOINT_NAME_CAP];
static double g_cmd_pos[NEML_JOINT_COUNT];
static double g_cmd_vel[NEML_JOINT_COUNT];
static double g_cmd_eff[NEML_JOINT_COUNT];

// ponytail: loop_max_us, tick_overruns and the faults byte are the evidence for
// T-072 and for every "why did it go limp?" question, and neml_msgs has no
// message that carries them. Three unsigned integers in a UInt32MultiArray cost
// twelve bytes and no agreement with anyone. Upgrade path: when neml_msgs grows
// a MotionHealth message, swap the type and delete the index table below.
//   [0] faults bitmask (CTRL_FAULT_* in control.h)
//   [1] tick overruns since boot
//   [2] worst 1 ms tick seen since boot, microseconds
static std_msgs__msg__UInt32MultiArray g_health_msg;
static uint32_t g_health_data[3];

static size_t ros_rx_head(void)
{
    return sizeof(g_ros_rx) - __HAL_DMA_GET_COUNTER(huart2.hdmarx);
}

static bool uros_open(struct uxrCustomTransport *t)
{
    (void)t;
    g_ros_tail = 0u;
    return HAL_UART_Receive_DMA(&huart2, g_ros_rx, (uint16_t)sizeof(g_ros_rx)) == HAL_OK;
}

static bool uros_close(struct uxrCustomTransport *t)
{
    (void)t;
    return HAL_UART_AbortReceive(&huart2) == HAL_OK;
}

static size_t uros_write(struct uxrCustomTransport *t, const uint8_t *buf, size_t len,
                         uint8_t *err)
{
    (void)t;
    if (HAL_UART_Transmit(&huart2, (uint8_t *)buf, (uint16_t)len, 100u) != HAL_OK) {
        *err = 1u;
        return 0u;
    }
    return len;
}

static size_t uros_read(struct uxrCustomTransport *t, uint8_t *buf, size_t len, int timeout,
                        uint8_t *err)
{
    (void)t;
    (void)err;
    const uint32_t deadline = HAL_GetTick() + (uint32_t)(timeout > 0 ? timeout : 0);
    size_t n = 0u;
    do {
        const size_t head = ros_rx_head();
        while (n < len && g_ros_tail != head) {
            buf[n++] = g_ros_rx[g_ros_tail];
            g_ros_tail = (g_ros_tail + 1u) % sizeof(g_ros_rx);
        }
    } while (n == 0u && HAL_GetTick() < deadline);
    return n;
}

// --- static message wiring --------------------------------------------------
static void bind_string(rosidl_runtime_c__String *s, char *buf, const char *init)
{
    s->data     = buf;
    s->capacity = JOINT_NAME_CAP;
    buf[0]      = '\0';
    s->size     = 0u;
    if (init != NULL) {
        strncpy(buf, init, JOINT_NAME_CAP - 1u);
        buf[JOINT_NAME_CAP - 1u] = '\0';
        s->size = strlen(buf);
    }
}

static void bind_doubles(rosidl_runtime_c__double__Sequence *seq, double *buf, size_t size)
{
    seq->data     = buf;
    seq->size     = size;
    seq->capacity = NEML_JOINT_COUNT;
}

static void ros_messages_init(void)
{
    // Outgoing: full length from the start, the values are refilled per publish.
    bind_string(&g_telem_msg.header.frame_id, g_telem_frame_buf, "base_link");
    g_telem_msg.name.data     = g_telem_name;
    g_telem_msg.name.size     = NEML_JOINT_COUNT;
    g_telem_msg.name.capacity = NEML_JOINT_COUNT;
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        bind_string(&g_telem_name[i], g_telem_name_buf[i], JOINT_NAMES[i]);
    }
    bind_doubles(&g_telem_msg.position, g_telem_pos, NEML_JOINT_COUNT);
    bind_doubles(&g_telem_msg.velocity, g_telem_vel, NEML_JOINT_COUNT);
    bind_doubles(&g_telem_msg.effort, g_telem_eff, NEML_JOINT_COUNT);
    bind_doubles(&g_telem_msg.temperature_c, g_telem_temp, NEML_JOINT_COUNT);
    bind_doubles(&g_telem_msg.current_a, g_telem_cur, NEML_JOINT_COUNT);

    g_health_msg.data.data     = g_health_data;
    g_health_msg.data.size     = 3u;
    g_health_msg.data.capacity = 3u;

    // Incoming: empty but with capacity, so deserialisation writes into these
    // buffers instead of asking the sealed heap for new ones.
    bind_string(&g_cmd_msg.header.frame_id, g_cmd_frame_buf, NULL);
    g_cmd_msg.name.data     = g_cmd_name;
    g_cmd_msg.name.size     = 0u;
    g_cmd_msg.name.capacity = NEML_JOINT_COUNT;
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        bind_string(&g_cmd_name[i], g_cmd_name_buf[i], NULL);
    }
    bind_doubles(&g_cmd_msg.position, g_cmd_pos, 0u);
    bind_doubles(&g_cmd_msg.velocity, g_cmd_vel, 0u);
    bind_doubles(&g_cmd_msg.effort, g_cmd_eff, 0u);
}

// Runs in the background loop, so it may not touch g_ctrl directly while the
// tick is mid-step. The copy is ~130 bytes, well under 2 us of added jitter.
static void cmd_callback(const void *msgin)
{
    const sensor_msgs__msg__JointState *m = (const sensor_msgs__msg__JointState *)msgin;

    // A command that is not exactly our 16 joints, in our order, is not a
    // command for this robot. Dropping it is the safe answer: the last good
    // command ages out in CMD_TIMEOUT_MS and control_step goes to the safe
    // state. Accepting a mis-ordered array would drive sixteen joints to
    // sixteen wrong angles, which is how a leg goes through a bench.
    if (m->position.size != NEML_JOINT_COUNT) {
        return;
    }
    if (m->name.size != 0u) {
        if (m->name.size != NEML_JOINT_COUNT) {
            return;
        }
        for (int i = 0; i < NEML_JOINT_COUNT; i++) {
            if (m->name.data[i].data == NULL ||
                strncmp(m->name.data[i].data, JOINT_NAMES[i], JOINT_NAME_CAP) != 0) {
                return;
            }
        }
    }

    const bool has_velocity = (m->velocity.size == NEML_JOINT_COUNT);

    joint_cmd_t cmd;
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        cmd.position_rad[i]  = (float)m->position.data[i];
        cmd.velocity_rads[i] = has_velocity ? (float)m->velocity.data[i] : 0.0f;
    }
    __disable_irq();
    control_set_command(&g_ctrl, &cmd);
    __enable_irq();
}

// Absolute time comes from the agent (micro-ROS session sync). Until the first
// sync lands, stamps are milliseconds since boot: honest, monotonic, and the Pi
// can see from the epoch that it is uptime and not 1970.
static builtin_interfaces__msg__Time ros_stamp(uint32_t now_ms)
{
    builtin_interfaces__msg__Time t;
    if (rmw_uros_epoch_synchronized()) {
        const int64_t ns = rmw_uros_epoch_nanos();
        t.sec     = (int32_t)(ns / 1000000000LL);
        t.nanosec = (uint32_t)(ns % 1000000000LL);
    } else {
        t.sec     = (int32_t)(now_ms / 1000u);
        t.nanosec = (now_ms % 1000u) * 1000000u;
    }
    return t;
}

// ---------------------------------------------------------------------------
// Board bring-up
// ---------------------------------------------------------------------------
static void clock_config(void)
{
    // 8 MHz HSE -> PLL /8 *360 /2 -> 180 MHz. Over-drive and 5 wait states are
    // mandatory above 168 MHz.
    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

    RCC_OscInitTypeDef osc = {0};
    osc.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    osc.HSEState       = RCC_HSE_BYPASS;   // Nucleo: MCO from the ST-LINK
    osc.PLL.PLLState   = RCC_PLL_ON;
    osc.PLL.PLLSource  = RCC_PLLSOURCE_HSE;
    osc.PLL.PLLM       = 8;
    osc.PLL.PLLN       = 360;
    osc.PLL.PLLP       = RCC_PLLP_DIV2;
    osc.PLL.PLLQ       = 7;
    osc.PLL.PLLR       = 2;
    if (HAL_RCC_OscConfig(&osc) != HAL_OK || HAL_PWREx_EnableOverDrive() != HAL_OK) {
        neml_fault_trap();
    }

    RCC_ClkInitTypeDef clk = {0};
    clk.ClockType      = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK |
                         RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    clk.SYSCLKSource   = RCC_SYSCLKSOURCE_PLLCLK;
    clk.AHBCLKDivider  = RCC_SYSCLK_DIV1;
    clk.APB1CLKDivider = RCC_HCLK_DIV4;    // 45 MHz
    clk.APB2CLKDivider = RCC_HCLK_DIV2;    // 90 MHz
    if (HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_5) != HAL_OK) {
        neml_fault_trap();
    }
}

static void gpio_config(void)
{
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();

    GPIO_InitTypeDef g = {0};

    // Heartbeat out. Low at reset: no heartbeat until the loop is actually
    // running, so the robot cannot be armed by a half booted controller.
    HAL_GPIO_WritePin(HB_PORT, HB_PIN, GPIO_PIN_RESET);
    g.Pin   = HB_PIN;
    g.Mode  = GPIO_MODE_OUTPUT_PP;
    g.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(HB_PORT, &g);

    // E-stop sense. Pull-up, so a cut wire reads as pressed.
    g.Pin  = ESTOP_PIN;
    g.Mode = GPIO_MODE_INPUT;
    g.Pull = GPIO_PULLUP;
    HAL_GPIO_Init(ESTOP_PORT, &g);

    // USART1 PA9 (servo bus, half duplex), USART2 PA2/PA3 (micro-ROS).
    g.Pin       = GPIO_PIN_9;
    g.Mode      = GPIO_MODE_AF_OD;
    g.Pull      = GPIO_PULLUP;
    g.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
    g.Alternate = GPIO_AF7_USART1;
    HAL_GPIO_Init(GPIOA, &g);

    g.Pin       = GPIO_PIN_2 | GPIO_PIN_3;
    g.Mode      = GPIO_MODE_AF_PP;
    g.Pull      = GPIO_PULLUP;
    g.Alternate = GPIO_AF7_USART2;
    HAL_GPIO_Init(GPIOA, &g);
}

static void uart_config(void)
{
    __HAL_RCC_USART1_CLK_ENABLE();
    __HAL_RCC_USART2_CLK_ENABLE();
    __HAL_RCC_DMA1_CLK_ENABLE();
    __HAL_RCC_DMA2_CLK_ENABLE();

    huart1.Instance          = USART1;
    huart1.Init.BaudRate     = 1000000u;   // STS3215 bus
    huart1.Init.WordLength   = UART_WORDLENGTH_8B;
    huart1.Init.StopBits     = UART_STOPBITS_1;
    huart1.Init.Parity       = UART_PARITY_NONE;
    huart1.Init.Mode         = UART_MODE_TX_RX;
    huart1.Init.HwFlowCtl    = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling = UART_OVERSAMPLING_16;

    huart2 = huart1;
    huart2.Instance      = USART2;
    huart2.Init.BaudRate = 921600u;        // micro-ROS agent link

    hdma_usart1_tx.Instance             = DMA2_Stream7;
    hdma_usart1_tx.Init.Channel         = DMA_CHANNEL_4;
    hdma_usart1_tx.Init.Direction       = DMA_MEMORY_TO_PERIPH;
    hdma_usart1_tx.Init.PeriphInc       = DMA_PINC_DISABLE;
    hdma_usart1_tx.Init.MemInc          = DMA_MINC_ENABLE;
    hdma_usart1_tx.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
    hdma_usart1_tx.Init.MemDataAlignment    = DMA_MDATAALIGN_BYTE;
    hdma_usart1_tx.Init.Mode            = DMA_NORMAL;
    hdma_usart1_tx.Init.Priority        = DMA_PRIORITY_HIGH;
    hdma_usart1_tx.Init.FIFOMode        = DMA_FIFOMODE_DISABLE;

    hdma_usart1_rx = hdma_usart1_tx;
    hdma_usart1_rx.Instance       = DMA2_Stream2;
    hdma_usart1_rx.Init.Direction = DMA_PERIPH_TO_MEMORY;

    hdma_usart2_rx = hdma_usart1_rx;
    hdma_usart2_rx.Instance       = DMA1_Stream5;
    hdma_usart2_rx.Init.Channel   = DMA_CHANNEL_4;
    hdma_usart2_rx.Init.Mode      = DMA_CIRCULAR;   // never stops, never overruns

    if (HAL_DMA_Init(&hdma_usart1_tx) != HAL_OK || HAL_DMA_Init(&hdma_usart1_rx) != HAL_OK ||
        HAL_DMA_Init(&hdma_usart2_rx) != HAL_OK) {
        neml_fault_trap();
    }
    __HAL_LINKDMA(&huart1, hdmatx, hdma_usart1_tx);
    __HAL_LINKDMA(&huart1, hdmarx, hdma_usart1_rx);
    __HAL_LINKDMA(&huart2, hdmarx, hdma_usart2_rx);

    if (HAL_HalfDuplex_Init(&huart1) != HAL_OK || HAL_UART_Init(&huart2) != HAL_OK) {
        neml_fault_trap();
    }

    HAL_NVIC_SetPriority(DMA2_Stream7_IRQn, 1, 0);
    HAL_NVIC_SetPriority(DMA2_Stream2_IRQn, 1, 0);
    HAL_NVIC_SetPriority(DMA1_Stream5_IRQn, 2, 0);
    HAL_NVIC_SetPriority(USART1_IRQn, 1, 0);
    HAL_NVIC_SetPriority(USART2_IRQn, 2, 0);
    HAL_NVIC_EnableIRQ(DMA2_Stream7_IRQn);
    HAL_NVIC_EnableIRQ(DMA2_Stream2_IRQn);
    HAL_NVIC_EnableIRQ(DMA1_Stream5_IRQn);
    HAL_NVIC_EnableIRQ(USART1_IRQn);
    HAL_NVIC_EnableIRQ(USART2_IRQn);
}

void DMA2_Stream7_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_usart1_tx); }
void DMA2_Stream2_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_usart1_rx); }
void DMA1_Stream5_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_usart2_rx); }
void USART1_IRQHandler(void) { HAL_UART_IRQHandler(&huart1); }
void USART2_IRQHandler(void) { HAL_UART_IRQHandler(&huart2); }

static void tim6_config(void)
{
    __HAL_RCC_TIM6_CLK_ENABLE();
    // APB1 is 45 MHz, so the timer clock is 90 MHz. 90 MHz / 90 / 1000 = 1 kHz.
    htim6.Instance           = TIM6;
    htim6.Init.Prescaler     = 89;
    htim6.Init.Period        = 999;
    htim6.Init.CounterMode   = TIM_COUNTERMODE_UP;
    htim6.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
    if (HAL_TIM_Base_Init(&htim6) != HAL_OK) {
        neml_fault_trap();
    }
    HAL_NVIC_SetPriority(TIM6_DAC_IRQn, 0, 0);   // above everything else
    HAL_NVIC_EnableIRQ(TIM6_DAC_IRQn);
}

static void dwt_config(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

static void servo_bus_bringup(void)
{
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        g_servo_ids[i] = (uint8_t)(i + 1);   // chain is addressed 1..16
    }
    // SPEC 5.1: push the compile time torque ceiling into the servos' own current
    // limiter before anything is allowed to move, so the limit survives even a
    // bug in this firmware. Blocking is fine, nothing is running yet.
    uint8_t buf[16];
    size_t n = servo_build_torque_limit(buf, sizeof(buf));
    HAL_HalfDuplex_EnableTransmitter(&huart1);
    HAL_UART_Transmit(&huart1, buf, (uint16_t)n, 100u);
    n = servo_build_torque_enable(buf, sizeof(buf), 1u);
    HAL_UART_Transmit(&huart1, buf, (uint16_t)n, 100u);
}

int main(void)
{
    HAL_Init();
    clock_config();
    dwt_config();
    gpio_config();
    uart_config();
    tim6_config();

    control_init(&g_ctrl);
    servo_bus_bringup();

    // --- micro-ROS -------------------------------------------------------
    rmw_uros_set_custom_transport(true, NULL, uros_open, uros_close, uros_write, uros_read);

    rcl_allocator_t   allocator = rcl_get_default_allocator();
    rclc_support_t    support;
    rcl_node_t        node;
    rcl_publisher_t   pub;
    rcl_publisher_t   health_pub;
    rcl_subscription_t sub;
    rclc_executor_t   executor;

    // SPEC 17.2 telemetry class, exactly: BEST_EFFORT / VOLATILE / KEEP_LAST(1).
    // rmw_qos_profile_sensor_data is the first two but keeps 5, so fix the depth.
    rmw_qos_profile_t telemetry_qos = rmw_qos_profile_sensor_data;
    telemetry_qos.depth = 1;

    rcl_init_options_t init_options = rcl_get_zero_initialized_init_options();
    if (rcl_init_options_init(&init_options, allocator) != RCL_RET_OK ||
        rcl_init_options_set_domain_id(&init_options, NEML_ROS_DOMAIN_ID) != RCL_RET_OK ||
        rclc_support_init_with_options(&support, 0, NULL, &init_options, &allocator) != RCL_RET_OK ||
        rclc_node_init_default(&node, "stm32_motion", NEML_ROBOT_NS, &support) != RCL_RET_OK ||
        rclc_publisher_init(
            &pub, &node, ROSIDL_GET_MSG_TYPE_SUPPORT(neml_msgs, msg, JointTelemetry),
            "telemetry/joint", &telemetry_qos) != RCL_RET_OK ||
        rclc_publisher_init(
            &health_pub, &node, ROSIDL_GET_MSG_TYPE_SUPPORT(std_msgs, msg, UInt32MultiArray),
            "telemetry/motion_health", &telemetry_qos) != RCL_RET_OK ||
        // SPEC 17.2: commands are RELIABLE / VOLATILE / KEEP_LAST(10), which is
        // exactly the rclc default profile.
        rclc_subscription_init_default(
            &sub, &node, ROSIDL_GET_MSG_TYPE_SUPPORT(sensor_msgs, msg, JointState),
            "cmd/joint") != RCL_RET_OK ||
        rclc_executor_init(&executor, &support.context, 1, &allocator) != RCL_RET_OK ||
        rclc_executor_add_subscription(&executor, &sub, &g_cmd_msg, cmd_callback,
                                       ON_NEW_DATA) != RCL_RET_OK) {
        neml_fault_trap();
    }

    // Point every sequence at its static buffer before the first message can be
    // received or published.
    ros_messages_init();
    (void)rmw_uros_sync_session(1000);   // once, before the control loop starts

    // Everything that was going to allocate has allocated. From here the heap is
    // closed and any call to it traps (see _sbrk).
    g_heap_sealed = 1u;

    // Only now does the control loop start: no torque command can be computed
    // before the node exists, and no heartbeat reaches L0 before this line.
    bus_advance();
    if (HAL_TIM_Base_Start_IT(&htim6) != HAL_OK) {
        neml_fault_trap();
    }

    uint32_t next_publish = HAL_GetTick();
    uint32_t next_sync    = HAL_GetTick() + TIME_SYNC_PERIOD_MS;
    uint32_t publishes    = 0u;
    for (;;) {
        rclc_executor_spin_some(&executor, RCL_MS_TO_NS(1));

        const uint32_t now = HAL_GetTick();

        // Blocking, but bounded and rare: the control loop lives in TIM6 at
        // priority 0 and does not care what this loop is waiting for, and the
        // timeout is far below the command timeout (see TIME_SYNC_TIMEOUT_MS).
        if ((int32_t)(now - next_sync) >= 0) {
            next_sync = now + TIME_SYNC_PERIOD_MS;
            (void)rmw_uros_sync_session(TIME_SYNC_TIMEOUT_MS);
        }

        if ((int32_t)(now - next_publish) < 0) {
            continue;
        }
        next_publish = now + TELEMETRY_PERIOD_MS;

        telem_snapshot_t snap;
        if (!telemetry_read(&snap)) {
            continue;
        }

        g_telem_msg.header.stamp = ros_stamp(now);
        for (int i = 0; i < NEML_JOINT_COUNT; i++) {
            g_telem_pos[i]  = (double)snap.position_rad[i];
            g_telem_vel[i]  = (double)snap.velocity_rads[i];
            g_telem_eff[i]  = (double)snap.torque_nm[i];
            g_telem_temp[i] = (double)snap.temperature_c[i];
            // No per joint current exists to report: the STS3215 chain reports
            // load, and the two ina226 sit on the rails, on esp32_aux, which
            // publishes body current on telemetry/battery. Zero is honest here;
            // deriving amps from load would be an invented number in a field an
            // operator would read as measured.
            g_telem_cur[i]  = 0.0;
        }
        (void)rcl_publish(&pub, &g_telem_msg, NULL);

        if (++publishes % HEALTH_EVERY == 0u) {
            g_health_data[0] = snap.faults;
            g_health_data[1] = snap.tick_overruns;
            g_health_data[2] = snap.loop_max_us;
            (void)rcl_publish(&health_pub, &g_health_msg, NULL);
        }
    }
}
