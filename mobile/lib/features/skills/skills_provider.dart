// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../core/network/api.dart';

final skillsProvider = FutureProvider<List<Skill>>(
  (ref) => ref.watch(apiProvider).skills(),
);

final skillVersionsProvider = FutureProvider.family<List<Skill>, String>(
  (ref, key) => ref.watch(apiProvider).skillVersions(key),
);
