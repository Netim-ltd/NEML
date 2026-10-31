// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/db/cache_db.dart';
import '../../core/models.dart';
import '../../core/network/api.dart';
import '../../core/network/online.dart';
import '../../core/realtime/live_client.dart';

/// Section 10.2 screen 10: level 4 also demands this word, typed by hand.
const kLevel4ConfirmWord = 'ONAYLIYORUM';

/// Why the current role may not decide this approval, or `null` when it may
/// (section 5.5: owner and operator decide; level 4 is owner only).
enum ApprovalBlock { notAuthorized, ownerOnly }

ApprovalBlock? approvalBlockReason(Session? session, int level) {
  if (session == null || !session.canApprove) return ApprovalBlock.notAuthorized;
  if (level >= 4 && !session.canApproveLevel4) return ApprovalBlock.ownerOnly;
  return null;
}

/// True only when the typed confirmation matches. Levels 1-3 need no text.
///
/// The match is exact, not trimmed: section 10.2 screen 10 says the operator
/// types "ONAYLIYORUM", and a level 4 gate (MANUFACTURE, section 5.2) is the
/// last thing standing between an LLM and a hot nozzle — section 5 never
/// relaxes. A keyboard that appends a space therefore holds the button down;
/// the field says why rather than leaving the operator guessing.
bool level4ConfirmationOk(int level, String typed) =>
    level < 4 || typed == kLevel4ConfirmWord;

/// Section 5.2 default window. The server sends `expiresAt`, so this is only
/// documentation of what that value normally is.
const kApprovalTimeout = Duration(hours: 24);

/// Section 5.2: an approval times out and is then auto-rejected server side.
/// Once that moment passes the phone must stop offering approval — the request
/// on screen is already dead.
///
/// The boundary counts as expired: at exactly `expiresAt` there is no window
/// left to approve in.
bool approvalExpired(DateTime? expiresAt, [DateTime? now]) =>
    expiresAt != null && !(now ?? DateTime.now()).isBefore(expiresAt);

class ApprovalsNotifier extends AsyncNotifier<List<Approval>> {
  @override
  Future<List<Approval>> build() async {
    ref.listen(liveEventsProvider, (_, next) {
      final event = next.value;
      if (event == null) return;
      if (event.name == 'ApprovalRequested' ||
          event.name == 'ApprovalDecided') {
        ref.invalidateSelf();
      }
    });
    return ref.read(apiProvider).approvals();
  }

  Future<void> approve(String id, String note) async {
    await ref.read(apiProvider).approve(id, note);
    ref.invalidateSelf();
  }

  /// Rejecting is the one write allowed to be queued while offline
  /// (section 10.3): the queued call throws [OfflineRejectionQueued] so the
  /// caller can tell the operator it was parked, not sent.
  Future<void> reject(String id, String note) async {
    await ref.read(apiProvider).rejectApproval(id, note);
    ref.invalidateSelf();
  }
}

final approvalsProvider =
    AsyncNotifierProvider<ApprovalsNotifier, List<Approval>>(
      ApprovalsNotifier.new,
    );

final approvalDetailProvider = FutureProvider.family<Approval, String>(
  (ref, id) => ref.watch(apiProvider).approval(id),
);

/// Drains the queued rejections as soon as the link is back. Watched by the
/// app shell so it runs for the whole session.
final rejectionFlusherProvider = Provider<void>((ref) {
  ref.listen(onlineProvider, (previous, next) async {
    if (next.online != true || previous?.online == true) return;
    final db = ref.read(cacheDbProvider);
    final api = ref.read(apiProvider);
    for (final pending in await db.pendingRejections()) {
      try {
        await api.rejectApproval(pending.approvalId, pending.note);
        await db.clearRejection(pending.approvalId);
      } on Object {
        // Still unreachable: leave it queued for the next reconnection.
        break;
      }
    }
    ref.invalidate(approvalsProvider);
  });
});
