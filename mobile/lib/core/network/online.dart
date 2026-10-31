// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Thrown (as `DioException.error`) when the operator tries to write while the
/// app is offline.
///
/// Section 10.3 is explicit: offline writes are **blocked, never queued**,
/// because a command that reaches a robot late is dangerous.
@immutable
class OfflineWriteBlocked implements Exception {
  const OfflineWriteBlocked();
}

/// The one exception to the rule above: an approval **rejection** errs on the
/// safe side, so it is parked in drift and replayed when the link returns.
@immutable
class OfflineRejectionQueued implements Exception {
  const OfflineRejectionQueued();
}

@immutable
class ConnStatus {
  const ConnStatus({required this.online, this.lastSync});

  final bool online;

  /// Timestamp of the newest cached payload — the "son guncelleme HH:mm" part
  /// of the offline banner.
  final DateTime? lastSync;

  ConnStatus copyWith({bool? online, DateTime? lastSync}) =>
      ConnStatus(online: online ?? this.online, lastSync: lastSync ?? this.lastSync);
}

/// Connectivity is inferred from what actually happened on the wire (dio
/// results and the SignalR hub), not from a radio-state plugin: a phone with
/// full bars but no route to the lab is offline for our purposes.
class OnlineNotifier extends Notifier<ConnStatus> {
  @override
  ConnStatus build() => const ConnStatus(online: true);

  void markOnline([DateTime? at]) {
    state = ConnStatus(online: true, lastSync: at ?? state.lastSync);
  }

  void markOffline([DateTime? lastSync]) {
    state = ConnStatus(online: false, lastSync: lastSync ?? state.lastSync);
  }
}

final onlineProvider = NotifierProvider<OnlineNotifier, ConnStatus>(
  OnlineNotifier.new,
);
