// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../shared/widgets.dart';
import 'brain_console_provider.dart';

/// Section 10.2 screen 6 — natural-language command in, detected intent and
/// generated change out, then the approval. The model never chooses tools
/// (section 4.3); this screen only shows what it classified.
class BrainConsoleView extends ConsumerStatefulWidget {
  const BrainConsoleView({super.key});

  @override
  ConsumerState<BrainConsoleView> createState() => _BrainConsoleViewState();
}

class _BrainConsoleViewState extends ConsumerState<BrainConsoleView> {
  final _input = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  Future<void> _send([String? text]) async {
    final value = text ?? _input.text;
    if (value.trim().isEmpty || _busy) return;
    setState(() => _busy = true);
    try {
      await ref.read(brainConsoleProvider.notifier).send(value);
      _input.clear();
    } on Object catch (e) {
      if (mounted) reportWriteResult(context, unwrapError(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = tr(context);
    final history = ref.watch(brainConsoleProvider);

    return NemlScaffold(
      title: l10n.brainConsole,
      actions: [
        IconButton(
          onPressed: () =>
              ref.read(brainConsoleProvider.notifier).refreshPending(),
          icon: const Icon(Icons.refresh),
          tooltip: l10n.refresh,
        ),
      ],
      body: Column(
        children: [
          Expanded(
            child: AsyncView<List<BrainCommand>>(
              history,
              builder: (items) => items.isEmpty
                  ? Center(child: Text(l10n.empty))
                  : ListView(
                      padding: const EdgeInsets.all(8),
                      children: [
                        for (final c in items) _CommandTurn(c),
                      ],
                    ),
            ),
          ),
          SizedBox(
            height: 44,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 8),
              children: [
                for (final template in kCommandTemplates)
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: ActionChip(
                      label: Text(template),
                      onPressed: _busy ? null : () => _send(template),
                    ),
                  ),
              ],
            ),
          ),
          Padding(
            padding: EdgeInsets.only(
              left: 8,
              right: 8,
              top: 4,
              bottom: MediaQuery.of(context).viewInsets.bottom + 8,
            ),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('brain-input'),
                    controller: _input,
                    onSubmitted: (_) => _send(),
                    decoration: InputDecoration(hintText: l10n.commandHint),
                  ),
                ),
                IconButton.filled(
                  key: const Key('brain-send'),
                  onPressed: _busy ? null : () => _send(),
                  icon: const Icon(Icons.send),
                  tooltip: l10n.send,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CommandTurn extends StatelessWidget {
  const _CommandTurn(this.command);

  final BrainCommand command;

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
                Expanded(
                  child: Text(
                    command.text,
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                ),
                StatusChip(command.state),
              ],
            ),
            if (command.intent != null)
              MetricTile(l10n.detectedIntent, command.intent!),
            if (command.change != null)
              MetricTile(l10n.generatedChange, command.change!),
            if (command.result != null)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text('${command.result}'),
              ),
          ],
        ),
      ),
    );
  }
}
