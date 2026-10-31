// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../shared/widgets.dart';
import 'evolution_provider.dart';

class EvolutionView extends ConsumerWidget {
  const EvolutionView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final state = ref.watch(evolutionProvider);

    return NemlScaffold(
      title: l10n.evolution,
      body: AsyncView<EvolutionState>(
        state,
        onRetry: () => ref.invalidate(evolutionProvider),
        builder: (data) {
          final campaign = data.campaign;
          if (campaign == null) return Center(child: Text(l10n.empty));
          return ListView(
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              campaign.name,
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                          ),
                          StatusChip(campaign.state),
                        ],
                      ),
                      Text(campaign.objective),
                      Row(
                        children: [
                          Expanded(
                            child: MetricTile(
                              l10n.generation,
                              '${campaign.generation}',
                            ),
                          ),
                          Expanded(
                            child: MetricTile(
                              l10n.bestFitness,
                              campaign.best?.toStringAsFixed(4) ?? '-',
                            ),
                          ),
                          Expanded(
                            child: MetricTile(
                              l10n.meanFitness,
                              campaign.mean?.toStringAsFixed(4) ?? '-',
                            ),
                          ),
                        ],
                      ),
                      MetricTile(
                        l10n.remainingBudget,
                        campaign.budgetRemaining?.toStringAsFixed(1) ?? '-',
                      ),
                      if (campaign.state == 'active')
                        Align(
                          alignment: Alignment.centerRight,
                          child: OutlinedButton.icon(
                            key: const Key('stop-campaign'),
                            onPressed: () async {
                              try {
                                await ref
                                    .read(evolutionProvider.notifier)
                                    .stop();
                              } on Object catch (e) {
                                if (context.mounted) {
                                  reportWriteResult(context, unwrapError(e));
                                }
                              }
                            },
                            icon: const Icon(Icons.stop_circle_outlined),
                            label: Text(l10n.stopCampaign),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
                child: Text(
                  l10n.fitnessCurve,
                  style: Theme.of(context).textTheme.titleSmall,
                ),
              ),
              SizedBox(
                height: 220,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(12, 8, 16, 8),
                  child: _FitnessChart(data.points),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
                child: Text(
                  l10n.candidates,
                  style: Theme.of(context).textTheme.titleSmall,
                ),
              ),
              if (data.candidates.isEmpty) ListTile(title: Text(l10n.empty)),
              for (final c in data.candidates)
                ListTile(
                  leading: CircleAvatar(child: Text('${c.generation}')),
                  title: Text(c.rationale ?? c.id),
                  subtitle: Text(
                    '${c.operator} - '
                    '${l10n.fitness} ${c.fitness?.toStringAsFixed(4) ?? '-'}',
                  ),
                  trailing: StatusChip(c.verdict ?? 'pending'),
                ),
            ],
          );
        },
      ),
    );
  }
}

class _FitnessChart extends StatelessWidget {
  const _FitnessChart(this.points);

  final List<GenerationPoint> points;

  @override
  Widget build(BuildContext context) {
    if (points.isEmpty) return Center(child: Text(tr(context).empty));
    final scheme = Theme.of(context).colorScheme;
    return LineChart(
      LineChartData(
        borderData: FlBorderData(show: false),
        lineTouchData: const LineTouchData(enabled: false),
        titlesData: const FlTitlesData(
          rightTitles: AxisTitles(),
          topTitles: AxisTitles(),
        ),
        lineBarsData: [
          LineChartBarData(
            color: scheme.primary,
            barWidth: 2,
            dotData: const FlDotData(show: false),
            spots: [
              for (final p in points)
                FlSpot(p.generation.toDouble(), p.best),
            ],
          ),
          LineChartBarData(
            color: scheme.secondary,
            barWidth: 2,
            dashArray: const [4, 4],
            dotData: const FlDotData(show: false),
            spots: [
              for (final p in points)
                FlSpot(p.generation.toDouble(), p.mean),
            ],
          ),
        ],
      ),
    );
  }
}
