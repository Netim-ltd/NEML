// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/models.dart';
import '../../shared/widgets.dart';
import 'tasks_provider.dart';

/// Section 10.2 screen 4 — queue / running / completed, swipe to reprioritise
/// or cancel, FAB for a new task.
class TasksView extends ConsumerWidget {
  const TasksView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final tasks = ref.watch(tasksProvider);

    return DefaultTabController(
      length: TaskTab.values.length,
      child: NemlScaffold(
        title: l10n.tasks,
        bottom: TabBar(
          tabs: [
            Tab(text: l10n.tabQueue),
            Tab(text: l10n.tabRunning),
            Tab(text: l10n.tabCompleted),
          ],
        ),
        floatingActionButton: FloatingActionButton(
          key: const Key('new-task-fab'),
          onPressed: () => _newTaskSheet(context, ref),
          child: const Icon(Icons.add),
        ),
        body: AsyncView<List<TaskItem>>(
          tasks,
          onRetry: () => ref.invalidate(tasksProvider),
          builder: (all) => TabBarView(
            children: [
              for (final tab in TaskTab.values)
                _TaskList(tasks: tasksForTab(all, tab), tab: tab),
            ],
          ),
        ),
      ),
    );
  }
}

class _TaskList extends ConsumerWidget {
  const _TaskList({required this.tasks, required this.tab});

  final List<TaskItem> tasks;
  final TaskTab tab;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    if (tasks.isEmpty) return Center(child: Text(l10n.empty));
    final closed = tab == TaskTab.completed;

    return ListView.builder(
      itemCount: tasks.length,
      itemBuilder: (context, i) {
        final task = tasks[i];
        final card = Card(
          child: ListTile(
            title: Text(task.title),
            subtitle: Row(
              children: [
                StatusChip(task.kind),
                const SizedBox(width: 6),
                StatusChip(task.state),
                const SizedBox(width: 6),
                Text('P${task.priority.toStringAsFixed(1)}'),
                if (task.robotId != null) Text('  ${task.robotId}'),
              ],
            ),
            trailing: task.progress == null
                ? null
                : SizedBox(
                    width: 40,
                    child: Text('${(task.progress! * 100).round()}%'),
                  ),
            onTap: () => context.go('/tasks/${task.id}'),
          ),
        );
        if (closed) return card;
        return Dismissible(
          key: Key('task-${task.id}'),
          background: _SwipeHint(
            icon: Icons.arrow_upward,
            label: l10n.raisePriority,
            alignment: Alignment.centerLeft,
          ),
          secondaryBackground: _SwipeHint(
            icon: Icons.cancel_outlined,
            label: l10n.cancelTask,
            alignment: Alignment.centerRight,
          ),
          confirmDismiss: (direction) async {
            final notifier = ref.read(tasksProvider.notifier);
            try {
              if (direction == DismissDirection.startToEnd) {
                await notifier.reprioritise(task.id, task.priority + 1);
              } else {
                await notifier.cancel(task.id);
              }
            } on Object catch (e) {
              if (context.mounted) reportWriteResult(context, unwrapError(e));
            }
            // The list is rebuilt from the server, never optimistically.
            return false;
          },
          child: card,
        );
      },
    );
  }
}

class _SwipeHint extends StatelessWidget {
  const _SwipeHint({
    required this.icon,
    required this.label,
    required this.alignment,
  });

  final IconData icon;
  final String label;
  final Alignment alignment;

  @override
  Widget build(BuildContext context) => Container(
    color: Theme.of(context).colorScheme.surfaceContainerHighest,
    alignment: alignment,
    padding: const EdgeInsets.symmetric(horizontal: 24),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [Icon(icon), const SizedBox(width: 8), Text(label)],
    ),
  );
}

Future<void> _newTaskSheet(BuildContext context, WidgetRef ref) async {
  final l10n = tr(context);
  final title = TextEditingController();
  final priority = TextEditingController(text: '1.0');
  var kind = 'human';

  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (sheetContext) => Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 16,
        bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 16,
      ),
      child: StatefulBuilder(
        builder: (builderContext, setState) => Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              key: const Key('new-task-title'),
              controller: title,
              decoration: InputDecoration(labelText: l10n.title),
            ),
            DropdownButtonFormField<String>(
              initialValue: kind,
              decoration: InputDecoration(labelText: l10n.kind),
              items: const [
                'human',
                'repair',
                'exploration',
                'evolution',
                'maintenance',
                'calibration',
              ].map((k) => DropdownMenuItem(value: k, child: Text(k))).toList(),
              onChanged: (v) => setState(() => kind = v ?? kind),
            ),
            TextField(
              controller: priority,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(labelText: l10n.priority),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: () async {
                try {
                  await ref
                      .read(tasksProvider.notifier)
                      .create(
                        title: title.text,
                        kind: kind,
                        priority: double.tryParse(priority.text) ?? 1,
                      );
                  if (sheetContext.mounted) Navigator.pop(sheetContext);
                } on Object catch (e) {
                  if (sheetContext.mounted) {
                    reportWriteResult(sheetContext, unwrapError(e));
                  }
                }
              },
              child: Text(l10n.submit),
            ),
          ],
        ),
      ),
    ),
  );
  title.dispose();
  priority.dispose();
}
