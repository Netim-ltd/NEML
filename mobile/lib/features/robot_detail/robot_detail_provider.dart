// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../core/network/api.dart';
import '../../core/realtime/live_client.dart';

/// The chart window of section 10.2 screen 3.
const kTelemetryWindow = Duration(seconds: 60);

/// Metrics the robot screen plots: battery, current, temperature, joint load.
const kTelemetryMetrics = <String>[
  'battery_soc',
  'current_a',
  'temperature_c',
  'joint_load',
];

/// Drops everything older than [kTelemetryWindow] relative to [now].
List<TelemetryPoint> trimWindow(List<TelemetryPoint> points, DateTime now) {
  final cutoff = now.subtract(kTelemetryWindow);
  return [for (final p in points) if (!p.ts.isBefore(cutoff)) p];
}

final robotProvider = FutureProvider.family<Robot, String>(
  (ref, id) => ref.watch(apiProvider).robot(id),
);

/// Tasks that ran on this robot, newest first (section 10.2 "son kosular").
final robotRunsProvider = FutureProvider.family<List<TaskItem>, String>((
  ref,
  id,
) async {
  final tasks = await ref.watch(apiProvider).tasks(robot: id);
  return tasks.reversed.take(10).toList();
});

/// 60 s rolling window per metric: seeded from the REST history, then kept up
/// to date by the 1 Hz `TelemetryTick` events of section 9.4.
final telemetryWindowProvider =
    StreamProvider.family<Map<String, List<TelemetryPoint>>, String>((
      ref,
      robotId,
    ) async* {
      final api = ref.watch(apiProvider);
      final now = DateTime.now();
      final window = <String, List<TelemetryPoint>>{};
      for (final metric in kTelemetryMetrics) {
        window[metric] = await api.telemetry(
          robotId,
          metric: metric,
          from: now.subtract(kTelemetryWindow),
          to: now,
        );
      }
      yield {...window};

      final client = ref.watch(liveClientProvider);
      if (client == null) return;
      unawaited(client.start().then((_) => client.subscribeRobot(robotId)));
      await for (final event in client.events) {
        if (event.name != 'TelemetryTick' ||
            '${event.data['robotId']}' != robotId) {
          continue;
        }
        final ts =
            DateTime.tryParse('${event.data['ts']}')?.toLocal() ??
            DateTime.now();
        final metrics = event.data['metrics'];
        if (metrics is! Map) continue;
        metrics.forEach((key, value) {
          final parsed = double.tryParse('$value');
          if (parsed == null) return;
          final series = window.putIfAbsent('$key', () => []);
          window['$key'] = trimWindow([
            ...series,
            TelemetryPoint(ts, '$key', parsed),
          ], ts);
        });
        yield {...window};
      }
    });

/// Queues the e-stop command (section 9.3). The UI gates this behind a
/// double-confirm slide; the hardware chain of section 5.1 is independent.
final estopProvider = Provider.family<Future<void> Function(), String>(
  (ref, robotId) => () => ref.read(apiProvider).estop(robotId),
);
