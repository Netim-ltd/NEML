// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../shared/widgets.dart';
import 'logs_provider.dart';

class LogsView extends ConsumerWidget {
  const LogsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final entries = ref.watch(logsProvider);
    final query = ref.watch(logFilterProvider);

    return DefaultTabController(
      length: LogTab.values.length,
      child: NemlScaffold(
        title: l10n.logs,
        bottom: TabBar(
          tabs: [
            Tab(text: l10n.auditLog),
            Tab(text: l10n.toolCalls),
            Tab(text: l10n.errors),
          ],
        ),
        actions: [
          IconButton(
            onPressed: () => ref.invalidate(logsProvider),
            icon: const Icon(Icons.refresh),
            tooltip: l10n.refresh,
          ),
        ],
        body: Column(
          children: [
            Padding(
              padding: const EdgeInsets.all(8),
              child: TextField(
                key: const Key('log-filter'),
                decoration: InputDecoration(
                  prefixIcon: const Icon(Icons.search),
                  labelText: l10n.filter,
                ),
                onChanged: ref.read(logFilterProvider.notifier).set,
              ),
            ),
            Expanded(
              child: AsyncView<List<AuditEntry>>(
                entries,
                onRetry: () => ref.invalidate(logsProvider),
                builder: (all) => TabBarView(
                  children: [
                    for (final tab in LogTab.values)
                      _LogList(logsForTab(all, tab, query)),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _LogList extends StatelessWidget {
  const _LogList(this.entries);

  final List<AuditEntry> entries;

  @override
  Widget build(BuildContext context) {
    final l10n = tr(context);
    if (entries.isEmpty) return Center(child: Text(l10n.empty));
    return ListView.builder(
      itemCount: entries.length,
      itemBuilder: (context, i) {
        final e = entries[i];
        return ListTile(
          leading: StatusChip(e.isError ? 'failed' : (e.outcome ?? 'idle')),
          title: Text(e.action),
          subtitle: Text(
            '${e.actor} -> ${e.target ?? '-'}  '
            '${dayTime.format(e.ts)}'
            '${e.durationMs == null ? '' : '  ${e.durationMs} ms'}',
          ),
        );
      },
    );
  }
}
