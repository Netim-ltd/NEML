// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../core/network/api.dart';
import '../../core/realtime/live_client.dart';

class DashboardState {
  const DashboardState({
    required this.brain,
    required this.robots,
    this.alerts = const [],
  });

  final BrainStatus brain;
  final List<Robot> robots;

  /// Newest first, capped at 5 (section 10.2 screen 2).
  final List<Alert> alerts;

  DashboardState copyWith({
    BrainStatus? brain,
    List<Robot>? robots,
    List<Alert>? alerts,
  }) => DashboardState(
    brain: brain ?? this.brain,
    robots: robots ?? this.robots,
    alerts: alerts ?? this.alerts,
  );
}

class DashboardNotifier extends AsyncNotifier<DashboardState> {
  @override
  Future<DashboardState> build() async {
    final api = ref.read(apiProvider);
    final brain = api.brainStatus();
    final robots = api.robots();
    ref.listen(liveEventsProvider, (_, next) {
      final event = next.value;
      if (event != null) _apply(event);
    });
    return DashboardState(brain: await brain, robots: await robots);
  }

  void _apply(LiveEvent event) {
    final current = state.value;
    if (current == null) return;
    switch (event.name) {
      case 'RobotState':
        final id = '${event.data['robotId']}';
        state = AsyncValue.data(
          current.copyWith(
            robots: [
              for (final r in current.robots)
                if (r.id == id) r.mergeLive(event.data) else r,
            ],
          ),
        );
      case 'BrainStatus':
        state = AsyncValue.data(
          current.copyWith(brain: BrainStatus.fromJson(event.data)),
        );
      case 'Alert':
        state = AsyncValue.data(
          current.copyWith(
            alerts: [
              Alert.fromJson(event.data),
              ...current.alerts,
            ].take(5).toList(),
          ),
        );
    }
  }

  Future<void> refresh() async {
    ref.invalidateSelf();
    await future;
  }
}

final dashboardProvider =
    AsyncNotifierProvider<DashboardNotifier, DashboardState>(
      DashboardNotifier.new,
    );
