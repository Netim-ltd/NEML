// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';

/// Material 3, dark by default (section 10.1).
const _seed = Color(0xFF00897B);

ThemeData _base(Brightness brightness) {
  final scheme = ColorScheme.fromSeed(seedColor: _seed, brightness: brightness);
  return ThemeData(
    colorScheme: scheme,
    useMaterial3: true,
    cardTheme: CardThemeData(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ),
    listTileTheme: const ListTileThemeData(dense: true),
  );
}

ThemeData get nemlLightTheme => _base(Brightness.light);
ThemeData get nemlDarkTheme => _base(Brightness.dark);

/// Colour for the lifecycle states of section 7 (robots, tasks, print jobs,
/// campaigns and genomes all funnel through here so one state reads the same
/// everywhere).
Color stateColor(ColorScheme scheme, String state) => switch (state) {
  'estop' || 'fault' || 'failed' || 'sim_fail' || 'real_fail' || 'rejected' =>
    scheme.error,
  'running' || 'printing' || 'active' || 'testing' => scheme.primary,
  'idle' || 'succeeded' || 'done' || 'validated' || 'accepted' ||
  'sim_pass' || 'real_pass' =>
    scheme.tertiary,
  'charging' || 'awaiting_approval' || 'paused' || 'planning' || 'pending' =>
    scheme.secondary,
  _ => scheme.outline,
};

/// Approval levels of section 5.2 — 4 (MANUFACTURE) is the one that also needs
/// a typed confirmation.
Color approvalLevelColor(ColorScheme scheme, int level) => switch (level) {
  4 => scheme.error,
  3 => scheme.errorContainer,
  2 => scheme.secondary,
  _ => scheme.tertiary,
};
