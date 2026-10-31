// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../shared/widgets.dart';
import 'task_detail_provider.dart';

class TaskDetailView extends ConsumerWidget {
  const TaskDetailView({super.key, required this.taskId});

  final String taskId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final task = ref.watch(taskDetailProvider(taskId));

    return NemlScaffold(
      title: l10n.tasks,
      drawer: false,
      body: AsyncView<TaskItem>(
        task,
        onRetry: () => ref.invalidate(taskDetailProvider(taskId)),
        builder: (data) => ListView(
          children: [
            ListTile(
              title: Text(data.title),
              subtitle: Row(
                children: [
                  StatusChip(data.kind),
                  const SizedBox(width: 6),
                  StatusChip(data.state),
                  const SizedBox(width: 6),
                  Text('P${data.priority.toStringAsFixed(1)}'),
                ],
              ),
            ),
            _Section(l10n.specJson),
            _Code(prettyJson(data.spec)),
            if (data.result != null) ...[
              _Section(l10n.metrics),
              _Code(prettyJson(data.result)),
            ],
            if (failureModesOf(data).isNotEmpty) ...[
              _Section(l10n.failureModes),
              for (final mode in failureModesOf(data))
                ListTile(
                  leading: const Icon(Icons.warning_amber_outlined),
                  title: Text(mode),
                ),
            ],
            _Section(l10n.runHistory),
            _Runs(taskId: taskId),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }
}

class _Runs extends ConsumerWidget {
  const _Runs({required this.taskId});

  final String taskId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final runs = ref.watch(taskRunsProvider(taskId));
    return AsyncView<List<TaskRun>>(
      runs,
      onRetry: () => ref.invalidate(taskRunsProvider(taskId)),
      builder: (items) => Column(
        children: [
          if (items.isEmpty) ListTile(title: Text(l10n.empty)),
          for (final run in items)
            ExpansionTile(
              leading: StatusChip(run.outcome ?? 'pending'),
              title: Text('${l10n.attempt} ${run.attempt} - ${run.env}'),
              subtitle: Text(
                run.startedAt == null ? '' : dayTime.format(run.startedAt!),
              ),
              children: [
                if (run.metrics.isNotEmpty) _Code(prettyJson(run.metrics)),
                if (run.rosbagPath != null)
                  ListTile(
                    leading: const Icon(Icons.download_outlined),
                    title: Text(l10n.downloadRosbag),
                    subtitle: Text(run.rosbagPath!),
                    // ponytail: no url_launcher in the dependency set of
                    // section 10.1, so the path is copied instead of opened.
                    onTap: () async {
                      await Clipboard.setData(
                        ClipboardData(text: run.rosbagPath!),
                      );
                      if (context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(content: Text(run.rosbagPath!)),
                        );
                      }
                    },
                  ),
              ],
            ),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
    child: Text(text, style: Theme.of(context).textTheme.titleSmall),
  );
}

class _Code extends StatelessWidget {
  const _Code(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    margin: const EdgeInsets.symmetric(horizontal: 12),
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      borderRadius: BorderRadius.circular(10),
    ),
    child: SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Text(text, style: const TextStyle(fontFamily: 'monospace')),
    ),
  );
}
