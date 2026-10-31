// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/network/api.dart';
import '../../shared/widgets.dart';
import 'board_data.dart';

/// The boards the agent team designed: one card per job, tap for the detail.
class BoardsView extends ConsumerWidget {
  const BoardsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final boards = ref.watch(boardsProvider);
    return NemlScaffold(
      title: 'Kartlar',
      actions: [
        IconButton(
          tooltip: 'Yenile',
          icon: const Icon(Icons.refresh),
          onPressed: () => ref.invalidate(boardsProvider),
        ),
      ],
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add),
        label: const Text('Yeni kart'),
        onPressed: () => _ask(context, ref),
      ),
      body: AsyncView<List<Map<String, dynamic>>>(
        boards,
        onRetry: () => ref.invalidate(boardsProvider),
        builder: (jobs) => jobs.isEmpty
            ? const Center(child: Text('Henüz kart yok.'))
            : RefreshIndicator(
                onRefresh: () async => ref.refresh(boardsProvider.future),
                child: ListView(
                  padding: const EdgeInsets.only(bottom: 88),
                  children: [for (final job in jobs) _BoardCard(job)],
                ),
              ),
      ),
    );
  }

  Future<void> _ask(BuildContext context, WidgetRef ref) async {
    final controller = TextEditingController();
    final messenger = ScaffoldMessenger.of(context);
    final brief = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Ne kartı?'),
        content: TextField(
          controller: controller,
          autofocus: true,
          maxLines: 3,
          decoration: const InputDecoration(
            hintText: 'Örn. IMU ve akım sensörü olan, 5 V girişli küçük kart',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Vazgeç'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, controller.text.trim()),
            child: const Text('Tasarla'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (brief == null || brief.isEmpty) return;
    try {
      await ref.read(apiProvider).learningOp({'op': 'board', 'brief': brief});
      messenger.showSnackBar(
        const SnackBar(
          content: Text('Ekip çalışmaya başladı; ilerleme kartta görünür.'),
        ),
      );
      ref.invalidate(boardsProvider);
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('$e')));
    }
  }
}

class _BoardCard extends StatelessWidget {
  const _BoardCard(this.job);

  final Map<String, dynamic> job;

  @override
  Widget build(BuildContext context) {
    final result = asMap(job['result']);
    final state = text(job['state']);
    final size = asList(result['size_mm']);
    final facts = <String>[
      if (size.length >= 2)
        '${number(size[0]).toStringAsFixed(0)} × ${number(size[1]).toStringAsFixed(0)} mm',
      if (result.isNotEmpty)
        result['clean'] == true ? 'yollar temiz' : 'yollar tam temiz değil',
      if (result.isNotEmpty)
        asMap(result['erc'])['passed'] == true ? 'ERC geçti' : 'ERC hata',
      if (result.isEmpty && job['error'] != null) text(job['error']),
    ];
    return Card(
      child: ListTile(
        title: Text(text(job['brief']), maxLines: 2),
        subtitle: Text(facts.join(' · '), maxLines: 3),
        trailing: StatusChip(state),
        onTap: () => context.push('/boards/${text(job['id'])}'),
      ),
    );
  }
}
