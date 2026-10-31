// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../core/network/api.dart';

final genomeTreeProvider = FutureProvider<List<GenomeNode>>(
  (ref) => ref.watch(apiProvider).genomeTree(),
);

class LineageRow {
  const LineageRow(this.node, this.depth);

  final GenomeNode node;
  final int depth;
}

/// Flattens `GET /genomes/tree` into the simple vertical lineage of
/// section 10.2 screen 8: roots first, each child indented under its parent.
List<LineageRow> lineageRows(List<GenomeNode> nodes) {
  final byParent = <String?, List<GenomeNode>>{};
  final ids = {for (final n in nodes) n.id};
  for (final n in nodes) {
    // A parent outside the returned set is treated as a root.
    final key = (n.parentId != null && ids.contains(n.parentId))
        ? n.parentId
        : null;
    byParent.putIfAbsent(key, () => []).add(n);
  }
  final rows = <LineageRow>[];
  void walk(String? parent, int depth) {
    final children = [...?byParent[parent]]
      ..sort((a, b) => a.version.compareTo(b.version));
    for (final child in children) {
      rows.add(LineageRow(child, depth));
      walk(child.id, depth + 1);
    }
  }

  walk(null, 0);
  return rows;
}
