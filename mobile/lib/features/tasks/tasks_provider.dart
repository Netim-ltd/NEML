// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../core/network/api.dart';
import '../../core/realtime/live_client.dart';

/// Tabs of section 10.2 screen 4.
enum TaskTab { queue, running, completed }

Set<String> statesOf(TaskTab tab) => switch (tab) {
  TaskTab.queue => TaskItem.queuedStates,
  TaskTab.running => TaskItem.runningStates,
  TaskTab.completed => TaskItem.doneStates,
};

/// Highest priority first inside a tab (section 7 index `state, priority DESC`).
List<TaskItem> tasksForTab(List<TaskItem> tasks, TaskTab tab) {
  final states = statesOf(tab);
  final rows = [for (final t in tasks) if (states.contains(t.state)) t]
    ..sort((a, b) => b.priority.compareTo(a.priority));
  return rows;
}

class TasksNotifier extends AsyncNotifier<List<TaskItem>> {
  @override
  Future<List<TaskItem>> build() async {
    ref.listen(liveEventsProvider, (_, next) {
      final event = next.value;
      if (event?.name == 'TaskUpdated') _applyUpdate(event!.data);
    });
    return ref.read(apiProvider).tasks();
  }

  void _applyUpdate(Map<String, dynamic> data) {
    final current = state.value;
    if (current == null) return;
    final id = '${data['taskId']}';
    state = AsyncValue.data([
      for (final t in current)
        if (t.id == id) t.mergeLive(data) else t,
    ]);
  }

  Future<void> reprioritise(String id, double priority) async {
    await ref.read(apiProvider).reprioritise(id, priority);
    ref.invalidateSelf();
  }

  Future<void> cancel(String id) async {
    await ref.read(apiProvider).cancelTask(id);
    ref.invalidateSelf();
  }

  Future<void> create({
    required String title,
    required String kind,
    required double priority,
    String? robotId,
  }) async {
    await ref
        .read(apiProvider)
        .createTask(
          title: title,
          kind: kind,
          priority: priority,
          robotId: robotId,
        );
    ref.invalidateSelf();
  }
}

final tasksProvider = AsyncNotifierProvider<TasksNotifier, List<TaskItem>>(
  TasksNotifier.new,
);
