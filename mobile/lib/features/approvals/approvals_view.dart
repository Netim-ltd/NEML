// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/auth/auth.dart';
import '../../core/models.dart';
import '../../core/theme/theme.dart';
import '../../shared/widgets.dart';
import 'approvals_provider.dart';

String formatRemaining(Duration d) => d.isNegative
    ? '00:00'
    : '${d.inHours.toString().padLeft(2, '0')}:'
          '${(d.inMinutes % 60).toString().padLeft(2, '0')}:'
          '${(d.inSeconds % 60).toString().padLeft(2, '0')}';

/// Rebuilds its child once a second so the section 5.2 countdown is live
/// rather than frozen at the moment the row was built, and so the approve
/// button goes dead the instant the window closes.
class ExpiryTicker extends StatefulWidget {
  const ExpiryTicker({
    super.key,
    required this.expiresAt,
    required this.builder,
  });

  final DateTime expiresAt;
  final Widget Function(BuildContext context, Duration remaining, bool expired)
  builder;

  @override
  State<ExpiryTicker> createState() => _ExpiryTickerState();
}

class _ExpiryTickerState extends State<ExpiryTicker> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    return widget.builder(
      context,
      widget.expiresAt.difference(now),
      approvalExpired(widget.expiresAt, now),
    );
  }
}

class ApprovalsView extends ConsumerWidget {
  const ApprovalsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final scheme = Theme.of(context).colorScheme;
    final approvals = ref.watch(approvalsProvider);
    return NemlScaffold(
      title: l10n.approvals,
      body: AsyncView<List<Approval>>(
        approvals,
        onRetry: () => ref.invalidate(approvalsProvider),
        builder: (items) => items.isEmpty
            ? Center(child: Text(l10n.empty))
            : ListView(
                children: [
                  for (final a in items)
                    ExpiryTicker(
                      expiresAt: a.expiresAt,
                      builder: (context, remaining, expired) => Card(
                        child: ListTile(
                          key: Key('approval-${a.id}'),
                          leading: _LevelBadge(a.level),
                          title: Text(
                            a.summary.isEmpty ? a.subjectId : a.summary,
                          ),
                          subtitle: Text(
                            '${a.subjectKind} - '
                            '${expired ? l10n.expired : l10n.remainingTime(formatRemaining(remaining))}',
                            style: expired
                                ? TextStyle(color: scheme.error)
                                : null,
                          ),
                          // Still tappable when expired: the operator may read
                          // what lapsed. Deciding it is what the detail blocks.
                          trailing: expired
                              ? Icon(Icons.block, color: scheme.error)
                              : null,
                          onTap: () => context.go('/approvals/${a.id}'),
                        ),
                      ),
                    ),
                ],
              ),
      ),
    );
  }
}

class _LevelBadge extends StatelessWidget {
  const _LevelBadge(this.level);

  final int level;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return CircleAvatar(
      backgroundColor: approvalLevelColor(scheme, level),
      child: Text('$level'),
    );
  }
}

class ApprovalDetailView extends ConsumerWidget {
  const ApprovalDetailView({super.key, required this.approvalId});

  final String approvalId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final detail = ref.watch(approvalDetailProvider(approvalId));
    return NemlScaffold(
      title: l10n.approvals,
      drawer: false,
      body: AsyncView<Approval>(
        detail,
        onRetry: () => ref.invalidate(approvalDetailProvider(approvalId)),
        builder: (a) => ListView(
          children: [
            ListTile(
              leading: _LevelBadge(a.level),
              title: Text(a.summary.isEmpty ? a.subjectId : a.summary),
              subtitle: Text('${a.subjectKind} / ${a.subjectId}'),
            ),
            _Countdown(a.expiresAt),
            Row(
              children: [
                Expanded(
                  child: MetricTile(
                    l10n.cost,
                    a.costTry == null
                        ? '-'
                        : '${a.costTry!.toStringAsFixed(2)} TRY',
                  ),
                ),
                Expanded(
                  child: MetricTile(
                    l10n.estimatedTime,
                    a.estTimeH == null
                        ? '-'
                        : '${a.estTimeH!.toStringAsFixed(1)} h',
                  ),
                ),
              ],
            ),
            if (a.previewUrl != null) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
                child: Text(
                  l10n.gcodePreview,
                  style: Theme.of(context).textTheme.titleSmall,
                ),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: Image.network(
                  a.previewUrl!,
                  errorBuilder: (_, _, _) => const Icon(Icons.broken_image),
                ),
              ),
            ],
            ApprovalDecisionPanel(
              level: a.level,
              expiresAt: a.expiresAt,
              onApprove: (note) =>
                  ref.read(approvalsProvider.notifier).approve(a.id, note),
              onReject: (note) =>
                  ref.read(approvalsProvider.notifier).reject(a.id, note),
            ),
          ],
        ),
      ),
    );
  }
}

class _Countdown extends StatelessWidget {
  const _Countdown(this.expiresAt);

  final DateTime expiresAt;

  @override
  Widget build(BuildContext context) {
    final l10n = tr(context);
    return ExpiryTicker(
      expiresAt: expiresAt,
      builder: (context, remaining, expired) => ListTile(
        leading: Icon(
          expired ? Icons.timer_off_outlined : Icons.timer_outlined,
          color: expired ? Theme.of(context).colorScheme.error : null,
        ),
        title: Text(
          expired ? l10n.expired : l10n.remainingTime(formatRemaining(remaining)),
        ),
      ),
    );
  }
}

/// Approve / reject with a note. Level 4 (MANUFACTURE, section 5.2) also
/// requires the operator to type [kLevel4ConfirmWord] by hand, and only the
/// owner may give it at all (section 5.5).
///
/// [expiresAt] is the section 5.2 timeout. Once it passes, approval is off the
/// table: the request is auto-rejected server side, so approving it here would
/// only produce a confusing failure. `null` means the caller knows of no
/// expiry.
class ApprovalDecisionPanel extends ConsumerStatefulWidget {
  const ApprovalDecisionPanel({
    super.key,
    required this.level,
    required this.onApprove,
    required this.onReject,
    this.expiresAt,
  });

  final int level;
  final DateTime? expiresAt;
  final Future<void> Function(String note) onApprove;
  final Future<void> Function(String note) onReject;

  @override
  ConsumerState<ApprovalDecisionPanel> createState() =>
      _ApprovalDecisionPanelState();
}

class _ApprovalDecisionPanelState extends ConsumerState<ApprovalDecisionPanel> {
  final _note = TextEditingController();
  final _confirm = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _note.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function(String note) action) async {
    setState(() => _busy = true);
    try {
      await action(_note.text);
      if (mounted) Navigator.of(context).maybePop();
    } on Object catch (e) {
      if (mounted) reportWriteResult(context, unwrapError(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => widget.expiresAt == null
      ? _panel(context, expired: false)
      : ExpiryTicker(
          expiresAt: widget.expiresAt!,
          builder: (context, _, expired) => _panel(context, expired: expired),
        );

  Widget _panel(BuildContext context, {required bool expired}) {
    final l10n = tr(context);
    final block = approvalBlockReason(ref.watch(sessionProvider), widget.level);
    final confirmed = level4ConfirmationOk(widget.level, _confirm.text);
    final canApprove = block == null && confirmed && !expired && !_busy;

    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            key: const Key('approval-note'),
            controller: _note,
            decoration: InputDecoration(labelText: l10n.note),
          ),
          if (widget.level >= 4) ...[
            const SizedBox(height: 12),
            TextField(
              key: const Key('level4-confirm'),
              controller: _confirm,
              onChanged: (_) => setState(() {}),
              // The match is exact, so the keyboard must not "help": no
              // autocorrect, no suggestion bar appending a trailing space.
              autocorrect: false,
              enableSuggestions: false,
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(
                labelText: l10n.level4ConfirmHint(kLevel4ConfirmWord),
                // Says so out loud once there is something to be wrong about.
                // A stray space is invisible; a dead button with no reason is
                // worse than a refusal with one.
                errorText: _confirm.text.isEmpty || confirmed
                    ? null
                    : l10n.level4ConfirmHint(kLevel4ConfirmWord),
              ),
            ),
          ],
          if (expired)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                l10n.expired,
                key: const Key('approval-expired'),
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
          if (block != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                block == ApprovalBlock.ownerOnly
                    ? l10n.ownerOnlyLevel4
                    : l10n.notAuthorizedToApprove,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: FilledButton(
                  key: const Key('approval-approve'),
                  onPressed: canApprove ? () => _run(widget.onApprove) : null,
                  child: Text(l10n.approve),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton(
                  key: const Key('approval-reject'),
                  // A rejection errs safe, so it needs neither the typed
                  // confirmation, nor a live connection (section 10.3), nor an
                  // unexpired window: an expired request is auto-rejected
                  // anyway, and saying so twice harms nothing.
                  onPressed: _busy || block == ApprovalBlock.notAuthorized
                      ? null
                      : () => _run(widget.onReject),
                  child: Text(l10n.reject),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
