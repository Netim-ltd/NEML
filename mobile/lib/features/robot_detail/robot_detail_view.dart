// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/models.dart';
import '../../shared/widgets.dart';
import 'robot_detail_provider.dart';

/// Section 10.2 screen 3 — live telemetry, state machine, recent runs, e-stop
/// behind a double-confirm slide, calibration status and reality gap.
class RobotDetailView extends ConsumerWidget {
  const RobotDetailView({super.key, required this.robotId});

  final String robotId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final robot = ref.watch(robotProvider(robotId));

    return NemlScaffold(
      title: robotId,
      drawer: false,
      body: AsyncView<Robot>(
        robot,
        onRetry: () => ref.invalidate(robotProvider(robotId)),
        builder: (data) => ListView(
          children: [
            _StateMachine(data.state),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: BatteryBar(data.batterySoc),
            ),
            Row(
              children: [
                Expanded(
                  child: MetricTile(
                    l10n.calibration,
                    data.calibratedAt == null
                        ? l10n.none
                        : dayTime.format(data.calibratedAt!),
                  ),
                ),
                Expanded(
                  child: MetricTile(
                    l10n.realityGap,
                    data.realityGap?.toStringAsFixed(3) ?? '-',
                  ),
                ),
              ],
            ),
            _TelemetryChart(robotId: robotId),
            _RecentRuns(robotId: robotId),
            Padding(
              padding: const EdgeInsets.all(16),
              child: ConfirmSlider(
                label: l10n.estop,
                confirmLabel: l10n.estopConfirmBody(robotId),
                onConfirmed: () async {
                  try {
                    await ref.read(estopProvider(robotId))();
                    ref.invalidate(robotProvider(robotId));
                  } on Object catch (e) {
                    if (context.mounted) {
                      reportWriteResult(context, unwrapError(e));
                    }
                  }
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// `offline -> idle -> charging -> running -> fault -> estop -> maintenance`
/// from section 7, with the current one highlighted.
class _StateMachine extends StatelessWidget {
  const _StateMachine(this.current);

  static const _states = [
    'offline',
    'idle',
    'charging',
    'running',
    'fault',
    'estop',
    'maintenance',
  ];

  final String current;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(tr(context).stateMachine, style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 6),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final s in _states)
              Opacity(opacity: s == current ? 1 : 0.35, child: StatusChip(s)),
          ],
        ),
      ],
    ),
  );
}

class _TelemetryChart extends ConsumerWidget {
  const _TelemetryChart({required this.robotId});

  final String robotId;

  static const _colors = [
    Colors.tealAccent,
    Colors.orangeAccent,
    Colors.redAccent,
    Colors.lightBlueAccent,
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final window = ref.watch(telemetryWindowProvider(robotId));
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(l10n.telemetry, style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 8),
          SizedBox(
            height: 220,
            child: AsyncView<Map<String, List<TelemetryPoint>>>(
              window,
              onRetry: () => ref.invalidate(telemetryWindowProvider(robotId)),
              builder: (series) {
                final now = DateTime.now();
                return LineChart(
                  LineChartData(
                    minX: -kTelemetryWindow.inSeconds.toDouble(),
                    maxX: 0,
                    borderData: FlBorderData(show: false),
                    titlesData: const FlTitlesData(show: false),
                    lineTouchData: const LineTouchData(enabled: false),
                    lineBarsData: [
                      for (var i = 0; i < kTelemetryMetrics.length; i++)
                        LineChartBarData(
                          color: _colors[i % _colors.length],
                          isCurved: true,
                          barWidth: 2,
                          dotData: const FlDotData(show: false),
                          spots: [
                            for (final p
                                in series[kTelemetryMetrics[i]] ??
                                    const <TelemetryPoint>[])
                              FlSpot(
                                p.ts.difference(now).inMilliseconds / 1000,
                                p.value,
                              ),
                          ],
                        ),
                    ],
                  ),
                );
              },
            ),
          ),
          const SizedBox(height: 6),
          Wrap(
            spacing: 12,
            children: [
              for (var i = 0; i < kTelemetryMetrics.length; i++)
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 10,
                      height: 10,
                      color: _colors[i % _colors.length],
                    ),
                    const SizedBox(width: 4),
                    Text(
                      switch (kTelemetryMetrics[i]) {
                        'battery_soc' => l10n.metricBattery,
                        'current_a' => l10n.metricCurrent,
                        'temperature_c' => l10n.metricTemperature,
                        _ => l10n.metricJointLoad,
                      },
                      style: Theme.of(context).textTheme.labelSmall,
                    ),
                  ],
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _RecentRuns extends ConsumerWidget {
  const _RecentRuns({required this.robotId});

  final String robotId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final runs = ref.watch(robotRunsProvider(robotId));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
          child: Text(
            l10n.recentRuns,
            style: Theme.of(context).textTheme.titleSmall,
          ),
        ),
        AsyncView<List<TaskItem>>(
          runs,
          onRetry: () => ref.invalidate(robotRunsProvider(robotId)),
          builder: (items) => Column(
            children: [
              if (items.isEmpty) ListTile(title: Text(l10n.empty)),
              for (final t in items)
                ListTile(
                  title: Text(t.title),
                  trailing: StatusChip(t.state),
                  onTap: () => context.go('/tasks/${t.id}'),
                ),
            ],
          ),
        ),
      ],
    );
  }
}
