// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../shared/widgets.dart';
import 'genome_tree_provider.dart';

class GenomeTreeView extends ConsumerWidget {
  const GenomeTreeView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final tree = ref.watch(genomeTreeProvider);

    return NemlScaffold(
      title: l10n.genomeTree,
      body: AsyncView<List<GenomeNode>>(
        tree,
        onRetry: () => ref.invalidate(genomeTreeProvider),
        builder: (nodes) {
          final rows = lineageRows(nodes);
          if (rows.isEmpty) return Center(child: Text(l10n.empty));
          return ListView.builder(
            itemCount: rows.length,
            itemBuilder: (context, i) {
              final row = rows[i];
              final active = row.node.status == 'active';
              return ListTile(
                contentPadding: EdgeInsets.only(
                  left: 16.0 + row.depth * 20,
                  right: 16,
                ),
                leading: Icon(
                  active ? Icons.star : Icons.subdirectory_arrow_right,
                  color: active ? Theme.of(context).colorScheme.tertiary : null,
                ),
                title: Text('${row.node.name} v${row.node.version}'),
                subtitle: Text(
                  active ? l10n.activeVersion : row.node.id,
                ),
                trailing: StatusChip(row.node.status),
                onTap: () => _summary(context, row.node),
              );
            },
          );
        },
      ),
    );
  }

  void _summary(BuildContext context, GenomeNode node) {
    final l10n = tr(context);
    showModalBottomSheet<void>(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              title: Text('${node.name} v${node.version}'),
              subtitle: Text(node.id),
              trailing: StatusChip(node.status),
            ),
            MetricTile(l10n.hash, node.hash.isEmpty ? '-' : node.hash),
            MetricTile(
              l10n.fitness,
              node.fitnessScore?.toStringAsFixed(4) ?? '-',
            ),
            MetricTile(l10n.status, node.status),
            const SizedBox(height: 16),
          ],
        ),
      ),
    );
  }
}
