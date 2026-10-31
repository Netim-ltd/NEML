// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../core/network/api.dart';

/// Registered push devices, shown as "oturumlar" (section 10.2 screen 13).
final devicesProvider = FutureProvider<List<DeviceSession>>(
  (ref) => ref.watch(apiProvider).devices(),
);
