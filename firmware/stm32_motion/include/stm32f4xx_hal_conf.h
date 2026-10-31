// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// NEML stm32_motion - STM32Cube HAL configuration.
//
// Only the modules this firmware actually uses are enabled. Adding one here adds
// code to a hard real-time target, so do not enable a module "just in case".
// The HAL itself is STM32CubeF4 (BSD-3-Clause), referenced from CMakeLists.txt
// and never copied into this tree.

#ifndef STM32F4xx_HAL_CONF_H
#define STM32F4xx_HAL_CONF_H

#define HAL_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_DMA_MODULE_ENABLED
#define HAL_FLASH_MODULE_ENABLED
#define HAL_GPIO_MODULE_ENABLED
#define HAL_PWR_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED
#define HAL_TIM_MODULE_ENABLED
#define HAL_UART_MODULE_ENABLED

// Nucleo-F446RE: 8 MHz MCO from the ST-LINK. A custom board with a crystal
// changes this one line and nothing else.
#define HSE_VALUE            8000000U
#define HSE_STARTUP_TIMEOUT  100U
#define HSI_VALUE            16000000U
#define LSI_VALUE            32000U
#define LSE_VALUE            32768U
#define LSE_STARTUP_TIMEOUT  5000U
#define EXTERNAL_CLOCK_VALUE 12288000U

#define VDD_VALUE                 3300U
#define TICK_INT_PRIORITY         0x0FU   // lowest: the control ISR outranks SysTick
#define USE_RTOS                  0U
#define PREFETCH_ENABLE           1U
#define INSTRUCTION_CACHE_ENABLE  1U
#define DATA_CACHE_ENABLE         1U
#define USE_HAL_UART_REGISTER_CALLBACKS 0U

#ifdef HAL_RCC_MODULE_ENABLED
#include "stm32f4xx_hal_rcc.h"
#endif
#ifdef HAL_GPIO_MODULE_ENABLED
#include "stm32f4xx_hal_gpio.h"
#endif
#ifdef HAL_DMA_MODULE_ENABLED
#include "stm32f4xx_hal_dma.h"
#endif
#ifdef HAL_CORTEX_MODULE_ENABLED
#include "stm32f4xx_hal_cortex.h"
#endif
#ifdef HAL_FLASH_MODULE_ENABLED
#include "stm32f4xx_hal_flash.h"
#endif
#ifdef HAL_PWR_MODULE_ENABLED
#include "stm32f4xx_hal_pwr.h"
#endif
#ifdef HAL_TIM_MODULE_ENABLED
#include "stm32f4xx_hal_tim.h"
#endif
#ifdef HAL_UART_MODULE_ENABLED
#include "stm32f4xx_hal_uart.h"
#endif

// No assert_param() in the control path: it would add a branch per HAL call and
// there is nothing sensible to do with the failure on a robot. Bad parameters
// are a build time problem here, not a runtime one.
#define assert_param(expr) ((void)0U)

#endif  // STM32F4xx_HAL_CONF_H
