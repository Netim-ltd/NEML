// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/models.dart';
import '../../shared/widgets.dart';
import '../approvals/approvals_provider.dart';
import 'dashboard_provider.dart';

class DashboardView extends ConsumerWidget {
  const DashboardView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final state = ref.watch(dashboardProvider);
    final pending = ref.watch(approvalsProvider).value?.length ?? 0;

    return NemlScaffold(
      title: l10n.dashboard,
      actions: [
        IconButton(
          onPressed: () => ref.read(dashboardProvider.notifier).refresh(),
          icon: const Icon(Icons.refresh),
          tooltip: l10n.refresh,
        ),
        _ApprovalBadge(count: pending),
      ],
      body: AsyncView<DashboardState>(
        state,
        onRetry: () => ref.invalidate(dashboardProvider),
        builder: (data) => LayoutBuilder(builder: (context, constraints) {
          final wide = constraints.maxWidth >= 800;
          return RefreshIndicator(
          onRefresh: () => ref.read(dashboardProvider.notifier).refresh(),
          child: ListView(
            children: [
              Center(child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 1200),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(12, 16, 12, 8),
                      child: wide
                          ? Row(crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Expanded(child: _BrainCard(data.brain)),
                                Expanded(child: _BudgetsCard(data.brain.budgets)),
                              ])
                          : Column(children: [
                              _BrainCard(data.brain),
                              _BudgetsCard(data.brain.budgets),
                            ]),
                    ),
                    _SectionTitle(l10n.robots),
                    if (wide)
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        child: Wrap(spacing: 8, runSpacing: 8, children: [
                          for (final robot in data.robots)
                            SizedBox(width: 350, child: _RobotCard(robot)),
                        ]),
                      )
                    else
                      for (final robot in data.robots) _RobotCard(robot),
                    _SectionTitle(l10n.lastAlerts),
                    if (data.alerts.isEmpty)
                      ListTile(title: Text(l10n.empty))
                    else
                      for (final alert in data.alerts)
                        ListTile(
                          leading: StatusChip(alert.severity),
                          title: Text(alert.message),
                          subtitle: Text('${alert.code} - ${hhmm.format(alert.ts)}'),
                        ),
                    const SizedBox(height: 24),
                  ],
                ),
              )),
            ],
          ),
        );
        }),
      ),
    );
  }
}

class _BudgetsCard extends StatelessWidget {
  const _BudgetsCard(this.budgets);

  final List<Budget> budgets;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(tr(context).dailyBudget,
            style: Theme.of(context).textTheme.titleMedium),
        for (final budget in budgets)
          BudgetBar(
            label: budget.key,
            ratio: budget.ratio,
            detail: '${budget.used.toStringAsFixed(0)} / '
                '${budget.limit.toStringAsFixed(0)} ${budget.unit}',
          ),
      ]),
    ),
  );
}

class _ApprovalBadge extends StatelessWidget {
  const _ApprovalBadge({required this.count});

  final int count;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(right: 8),
    child: Badge(
      key: const Key('pending-approval-badge'),
      isLabelVisible: count > 0,
      label: Text('$count'),
      child: IconButton(
        icon: const Icon(Icons.verified_user_outlined),
        tooltip: tr(context).pendingApprovals,
        onPressed: () => context.go('/approvals'),
      ),
    ),
  );
}

class _BrainCard extends StatelessWidget {
  const _BrainCard(this.brain);

  final BrainStatus brain;

  @override
  Widget build(BuildContext context) {
    final l10n = tr(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  l10n.brainStatus,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const Spacer(),
                StatusChip(
                  brain.online ? 'running' : 'offline',
                  label: brain.online ? l10n.online : l10n.offline,
                ),
              ],
            ),
            Row(
              children: [
                Expanded(child: MetricTile(l10n.model, brain.model)),
                Expanded(child: MetricTile(l10n.gpuOwner, brain.gpuOwner)),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _RobotCard extends StatelessWidget {
  const _RobotCard(this.robot);

  final Robot robot;

  @override
  Widget build(BuildContext context) {
    final l10n = tr(context);
    return Card(
      child: InkWell(
        onTap: () => context.go('/robots/${robot.id}'),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text(
                    robot.id,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(width: 8),
                  StatusChip(robot.state),
                ],
              ),
              const SizedBox(height: 6),
              BatteryBar(robot.batterySoc),
              const SizedBox(height: 4),
              Text('${l10n.currentTask}: ${robot.currentTask ?? l10n.none}'),
            ],
          ),
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
    child: Text(text, style: Theme.of(context).textTheme.titleSmall),
  );
}
