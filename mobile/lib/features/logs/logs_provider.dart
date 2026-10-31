// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../core/network/api.dart';

/// Section 10.2 screen 12 — audit log, agent tool calls, error stream.
enum LogTab { audit, toolCalls, errors }

List<AuditEntry> logsForTab(
  List<AuditEntry> entries,
  LogTab tab,
  String query,
) {
  final needle = query.trim().toLowerCase();
  return [
    for (final e in entries)
      if (switch (tab) {
            LogTab.audit => true,
            LogTab.toolCalls => e.isToolCall,
            LogTab.errors => e.isError,
          } &&
          (needle.isEmpty ||
              e.actor.toLowerCase().contains(needle) ||
              e.action.toLowerCase().contains(needle) ||
              (e.target ?? '').toLowerCase().contains(needle)))
        e,
  ];
}

final logsProvider = FutureProvider<List<AuditEntry>>(
  (ref) async => await ref.watch(apiProvider).audit(),
);

class LogFilter extends Notifier<String> {
  @override
  String build() => '';

  void set(String value) => state = value;
}

final logFilterProvider = NotifierProvider<LogFilter, String>(LogFilter.new);
