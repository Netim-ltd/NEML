// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../core/network/api.dart';
import '../../core/realtime/live_client.dart';

class EvolutionState {
  const EvolutionState({
    this.campaign,
    this.points = const [],
    this.candidates = const [],
  });

  final Campaign? campaign;
  final List<GenerationPoint> points;
  final List<Candidate> candidates;

  EvolutionState copyWith({
    Campaign? campaign,
    List<GenerationPoint>? points,
    List<Candidate>? candidates,
  }) => EvolutionState(
    campaign: campaign ?? this.campaign,
    points: points ?? this.points,
    candidates: candidates ?? this.candidates,
  );
}

/// Section 10.2 screen 7 — the active campaign, its fitness curve and the
/// candidate verdicts.
class EvolutionNotifier extends AsyncNotifier<EvolutionState> {
  @override
  Future<EvolutionState> build() async {
    ref.listen(liveEventsProvider, (_, next) {
      final event = next.value;
      if (event?.name == 'CampaignProgress') _applyProgress(event!.data);
    });

    final campaigns = await ref.read(apiProvider).campaigns();
    if (campaigns.isEmpty) return const EvolutionState();
    final active = campaigns.firstWhere(
      (c) => c.state == 'active',
      orElse: () => campaigns.first,
    );
    final api = ref.read(apiProvider);
    final points = api.generations(active.id);
    final candidates = api.candidates(active.id);
    return EvolutionState(
      campaign: active,
      points: await points,
      candidates: await candidates,
    );
  }

  void _applyProgress(Map<String, dynamic> data) {
    final current = state.value;
    final campaign = current?.campaign;
    if (current == null ||
        campaign == null ||
        '${data['campaignId']}' != campaign.id) {
      return;
    }
    final updated = campaign.mergeProgress(data);
    final point = GenerationPoint(
      updated.generation,
      updated.best ?? 0,
      updated.mean ?? 0,
    );
    state = AsyncValue.data(
      current.copyWith(
        campaign: updated,
        points: [
          for (final p in current.points)
            if (p.generation != point.generation) p,
          point,
        ]..sort((a, b) => a.generation.compareTo(b.generation)),
      ),
    );
  }

  Future<void> stop() async {
    final id = state.value?.campaign?.id;
    if (id == null) return;
    await ref.read(apiProvider).stopCampaign(id);
    ref.invalidateSelf();
  }
}

final evolutionProvider =
    AsyncNotifierProvider<EvolutionNotifier, EvolutionState>(
      EvolutionNotifier.new,
    );
