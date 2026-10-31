// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../core/network/online.dart';
import '../core/theme/theme.dart';
import '../l10n/app_localizations.dart';

final hhmm = DateFormat('HH:mm');
final dayTime = DateFormat('dd.MM HH:mm');

AppLocalizations tr(BuildContext context) => AppLocalizations.of(context)!;

/// Coloured pill for any lifecycle state of section 7.
class StatusChip extends StatelessWidget {
  const StatusChip(this.state, {super.key, this.label});

  final String state;
  final String? label;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final color = stateColor(scheme, state);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.18),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color),
      ),
      child: Text(
        label ?? state,
        style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600),
      ),
    );
  }
}

class MetricTile extends StatelessWidget {
  const MetricTile(this.label, this.value, {super.key, this.icon});

  final String label;
  final String value;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              if (icon != null) ...[Icon(icon, size: 14), const SizedBox(width: 4)],
              Text(label, style: text.labelSmall),
            ],
          ),
          Text(value, style: text.titleMedium),
        ],
      ),
    );
  }
}

class BatteryBar extends StatelessWidget {
  const BatteryBar(this.soc, {super.key});

  /// State of charge, 0..1 (`robots.battery_soc`, section 7).
  final double? soc;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final value = (soc ?? 0).clamp(0.0, 1.0);
    return Row(
      children: [
        const Icon(Icons.battery_std, size: 16),
        const SizedBox(width: 6),
        Expanded(
          child: LinearProgressIndicator(
            value: value,
            minHeight: 8,
            color: value < 0.3 ? scheme.error : scheme.tertiary,
          ),
        ),
        const SizedBox(width: 6),
        Text('${(value * 100).round()}%'),
      ],
    );
  }
}

/// Labelled progress bar used for the daily budget rows (section 14.4).
class BudgetBar extends StatelessWidget {
  const BudgetBar({
    super.key,
    required this.label,
    required this.ratio,
    required this.detail,
  });

  final String label;
  final double ratio;
  final String detail;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(label, style: Theme.of(context).textTheme.labelMedium),
              Text(detail, style: Theme.of(context).textTheme.labelSmall),
            ],
          ),
          const SizedBox(height: 2),
          LinearProgressIndicator(
            value: ratio,
            minHeight: 6,
            // Section 14.4 notifies at 90%; make that visible too.
            color: ratio >= 0.9 ? scheme.error : scheme.primary,
          ),
        ],
      ),
    );
  }
}

/// Two-pass slide confirmation. Used for the e-stop of section 10.2 screen 3:
/// one accidental swipe is not enough to command a robot to stop.
class ConfirmSlider extends StatefulWidget {
  const ConfirmSlider({
    super.key,
    required this.label,
    required this.confirmLabel,
    required this.onConfirmed,
  });

  final String label;
  final String confirmLabel;
  final VoidCallback onConfirmed;

  @override
  State<ConfirmSlider> createState() => _ConfirmSliderState();
}

class _ConfirmSliderState extends State<ConfirmSlider> {
  double _value = 0;
  int _passes = 0;

  void _end(double v) {
    if (v >= 0.99) {
      _passes++;
      if (_passes >= 2) {
        _passes = 0;
        widget.onConfirmed();
      }
    }
    setState(() => _value = 0);
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Column(
      children: [
        Text(
          _passes == 0 ? widget.label : widget.confirmLabel,
          key: const Key('confirm-slider-label'),
          style: TextStyle(color: scheme.error, fontWeight: FontWeight.bold),
        ),
        Slider(
          key: const Key('confirm-slider'),
          value: _value,
          activeColor: scheme.error,
          onChanged: (v) => setState(() => _value = v),
          onChangeEnd: _end,
        ),
      ],
    );
  }
}

class ErrorView extends StatelessWidget {
  const ErrorView(this.error, {super.key, this.onRetry});

  final Object error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(Icons.error_outline, color: Theme.of(context).colorScheme.error),
        Padding(
          padding: const EdgeInsets.all(12),
          child: Text('$error', textAlign: TextAlign.center),
        ),
        if (onRetry != null)
          FilledButton.tonal(onPressed: onRetry, child: Text(tr(context).retry)),
      ],
    ),
  );
}

/// Section 10.3 banner. Visible whenever the app is serving cached data.
class OfflineBanner extends ConsumerWidget {
  const OfflineBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final conn = ref.watch(onlineProvider);
    if (conn.online) return const SizedBox.shrink();
    final scheme = Theme.of(context).colorScheme;
    return Material(
      color: scheme.errorContainer,
      child: SizedBox(
        width: double.infinity,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 12),
          child: Text(
            tr(context).offlineBanner(
              conn.lastSync == null ? '--:--' : hhmm.format(conn.lastSync!),
            ),
            key: const Key('offline-banner'),
            textAlign: TextAlign.center,
            style: TextStyle(color: scheme.onErrorContainer),
          ),
        ),
      ),
    );
  }
}

/// Turns the offline exceptions of section 10.3 into the operator-facing
/// message. Every write in the app funnels through here, so the blocked /
/// queued asymmetry is stated once.
void reportWriteResult(BuildContext context, Object error) {
  final l10n = tr(context);
  final message = switch (error) {
    OfflineWriteBlocked() => l10n.offlineWriteBlocked,
    OfflineRejectionQueued() => l10n.offlineRejectionQueued,
    _ => '$error',
  };
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
}

/// Unwraps a [DioException] so [reportWriteResult] sees our own error types.
Object unwrapError(Object error) =>
    error is DioException ? (error.error ?? error) : error;

/// The 13 screens of section 10.2, in spec order.
const kDestinations = <(String path, IconData icon)>[
  ('/', Icons.dashboard_outlined),
  ('/tasks', Icons.checklist),
  ('/brain', Icons.psychology_outlined),
  ('/evolution', Icons.trending_up),
  ('/genomes', Icons.account_tree_outlined),
  ('/skills', Icons.library_books_outlined),
  ('/approvals', Icons.verified_user_outlined),
  ('/manufacturing', Icons.precision_manufacturing_outlined),
  ('/boards', Icons.memory),
  ('/logs', Icons.receipt_long_outlined),
  ('/settings', Icons.settings_outlined),
];

String destinationLabel(AppLocalizations l10n, String path) => switch (path) {
  '/' => l10n.dashboard,
  '/tasks' => l10n.tasks,
  '/brain' => l10n.brainConsole,
  '/evolution' => l10n.evolution,
  '/genomes' => l10n.genomeTree,
  '/skills' => l10n.skills,
  '/approvals' => l10n.approvals,
  '/manufacturing' => l10n.manufacturing,
  '/boards' => l10n.localeName.startsWith('tr') ? 'Kartlar' : 'Boards',
  '/logs' => l10n.logs,
  _ => l10n.settings,
};

/// Scaffold shared by every screen: offline banner pinned above the body plus
/// the section drawer.
class NemlScaffold extends StatelessWidget {
  const NemlScaffold({
    super.key,
    required this.title,
    required this.body,
    this.actions,
    this.floatingActionButton,
    this.bottom,
    this.drawer = true,
  });

  final String title;
  final Widget body;
  final List<Widget>? actions;
  final Widget? floatingActionButton;
  final PreferredSizeWidget? bottom;
  final bool drawer;

  @override
  Widget build(BuildContext context) {
    final l10n = tr(context);
    final path = GoRouter.maybeOf(context)?.routeInformationProvider.value.uri.path
        ?? '/';
    return LayoutBuilder(builder: (context, constraints) {
      final wide = constraints.maxWidth >= 960;
      final extended = constraints.maxWidth >= 1280;
      final selected = kDestinations.indexWhere((destination) =>
          destination.$1 == '/' ? path == '/' :
          path == destination.$1 || path.startsWith('${destination.$1}/'));
      final content = Column(
        children: [const OfflineBanner(), Expanded(child: body)],
      );
      return Scaffold(
      appBar: AppBar(title: Text(title), actions: actions, bottom: bottom),
      drawer: drawer && !wide
          ? Drawer(
              child: ListView(
                padding: EdgeInsets.zero,
                children: [
                  DrawerHeader(child: Text(l10n.appTitle)),
                  for (final (path, icon) in kDestinations)
                    ListTile(
                      leading: Icon(icon),
                      title: Text(destinationLabel(l10n, path)),
                      onTap: () {
                        Navigator.pop(context);
                        context.go(path);
                      },
                    ),
                ],
              ),
            )
          : null,
      floatingActionButton: floatingActionButton,
      body: wide
          ? Row(children: [
              NavigationRail(
                key: const Key('desktop-navigation'),
                extended: extended,
                selectedIndex: selected < 0 ? 0 : selected,
                labelType: extended ? NavigationRailLabelType.none :
                    NavigationRailLabelType.selected,
                leading: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  child: Icon(Icons.hub_outlined,
                      color: Theme.of(context).colorScheme.primary),
                ),
                destinations: [
                  for (final (route, icon) in kDestinations)
                    NavigationRailDestination(
                      icon: Icon(icon),
                      label: Text(destinationLabel(l10n, route)),
                    ),
                ],
                onDestinationSelected: (index) =>
                    context.go(kDestinations[index].$1),
              ),
              const VerticalDivider(width: 1),
              Expanded(child: content),
            ])
          : content,
    );
    });
  }
}

/// `AsyncValue` boilerplate, written once.
class AsyncView<T> extends StatelessWidget {
  const AsyncView(this.value, {super.key, required this.builder, this.onRetry});

  final AsyncValue<T> value;
  final Widget Function(T data) builder;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) => value.when(
    data: builder,
    loading: () => const Center(child: CircularProgressIndicator()),
    error: (e, _) => ErrorView(e, onRetry: onRetry),
  );
}
