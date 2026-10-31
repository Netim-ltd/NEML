// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../core/network/api.dart';

/// Ready-made commands offered as chips (section 10.2 screen 6).
const kCommandTemplates = <String>[
  'R01 durumunu ozetle',
  'Bekleyen onaylari listele',
  'Gunluk butce durumunu goster',
  'Aktif kampanyayi durdur',
  'R01 icin kalibrasyon gorevi olustur',
];

/// Chat-like history of the console. Kept in memory for the session: the
/// authoritative record is `commands` and `audit_log` on the server.
class BrainConsoleNotifier extends AsyncNotifier<List<BrainCommand>> {
  @override
  List<BrainCommand> build() => const [];

  Future<void> send(String text) async {
    if (text.trim().isEmpty) return;
    final api = ref.read(apiProvider);
    final history = state.value ?? const <BrainCommand>[];
    final sent = await api.sendCommand(text.trim());
    state = AsyncValue.data([...history, sent]);

    // The brain applies the command asynchronously; pull the detected intent
    // and the generated change once it has been classified (section 4.3).
    try {
      final resolved = await api.command(sent.id);
      state = AsyncValue.data([
        for (final c in state.value ?? const <BrainCommand>[])
          if (c.id == sent.id) c.mergeResult(resolved) else c,
      ]);
    } on Object {
      // Leave the turn as pending; the operator can pull to refresh.
    }
  }

  Future<void> refreshPending() async {
    final api = ref.read(apiProvider);
    final history = state.value ?? const <BrainCommand>[];
    final updated = <BrainCommand>[];
    for (final c in history) {
      if (c.state == 'applied' || c.state == 'failed' || c.state == 'rejected') {
        updated.add(c);
        continue;
      }
      try {
        updated.add(c.mergeResult(await api.command(c.id)));
      } on Object {
        updated.add(c);
      }
    }
    state = AsyncValue.data(updated);
  }
}

final brainConsoleProvider =
    AsyncNotifierProvider<BrainConsoleNotifier, List<BrainCommand>>(
      BrainConsoleNotifier.new,
    );
