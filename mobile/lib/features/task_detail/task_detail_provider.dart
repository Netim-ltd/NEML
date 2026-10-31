// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../core/network/api.dart';

final taskDetailProvider = FutureProvider.family<TaskItem, String>(
  (ref, id) => ref.watch(apiProvider).task(id),
);

final taskRunsProvider = FutureProvider.family<List<TaskRun>, String>(
  (ref, id) => ref.watch(apiProvider).runs(id),
);

/// Indented JSON for the spec viewer of section 10.2 screen 5.
String prettyJson(Object? value) =>
    const JsonEncoder.withIndent('  ').convert(value);

/// Failure modes recorded on the task result (section 14.6).
List<String> failureModesOf(TaskItem task) {
  final modes = task.result?['failure_modes'] ?? task.result?['failureModes'];
  return modes is List ? [for (final m in modes) '$m'] : const [];
}
