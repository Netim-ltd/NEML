// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'auth/token_store.dart';

/// Default remote API host, matching `NEML_CLOUD_WS` in section 17.3.
/// The operator can point the app at another server from the login or the
/// settings screen (section 10.2 screens 1 and 13).
// A release build can bake in its own server: --dart-define=NEML_SERVER_URL=https://host
const kDefaultServerUrl =
    String.fromEnvironment('NEML_SERVER_URL', defaultValue: 'https://api.neml.easyway-sharing.com');

/// Push triggers of section 10.4, in the spec's own order.
const kPushTriggers = <String>[
  'approval_requested',
  'robot_fault',
  'task_failed',
  'campaign_completed',
  'print_finished',
  'budget_90',
];

/// Everything the operator can change under Settings. Persisted as one JSON
/// blob; secure storage is the only key/value store this app depends on.
@immutable
class AppSettings {
  const AppSettings({
    this.serverUrl = kDefaultServerUrl,
    this.themeMode = ThemeMode.dark,
    this.localeCode = 'tr',
    this.biometricLock = false,
    this.mutedTriggers = const <String>{},
  });

  factory AppSettings.fromJson(Map<String, dynamic> j) => AppSettings(
    serverUrl: (j['serverUrl'] as String?) ?? kDefaultServerUrl,
    themeMode: ThemeMode.values.firstWhere(
      (m) => m.name == j['themeMode'],
      orElse: () => ThemeMode.dark,
    ),
    localeCode: (j['localeCode'] as String?) ?? 'tr',
    biometricLock: j['biometricLock'] == true,
    mutedTriggers: {...?(j['mutedTriggers'] as List?)?.map((e) => '$e')},
  );

  final String serverUrl;

  /// Material 3 dark by default (section 10.1).
  final ThemeMode themeMode;

  /// TR primary, EN secondary (section 10.1).
  final String localeCode;
  final bool biometricLock;
  final Set<String> mutedTriggers;

  Map<String, dynamic> toJson() => {
    'serverUrl': serverUrl,
    'themeMode': themeMode.name,
    'localeCode': localeCode,
    'biometricLock': biometricLock,
    'mutedTriggers': mutedTriggers.toList(),
  };

  AppSettings copyWith({
    String? serverUrl,
    ThemeMode? themeMode,
    String? localeCode,
    bool? biometricLock,
    Set<String>? mutedTriggers,
  }) => AppSettings(
    serverUrl: serverUrl ?? this.serverUrl,
    themeMode: themeMode ?? this.themeMode,
    localeCode: localeCode ?? this.localeCode,
    biometricLock: biometricLock ?? this.biometricLock,
    mutedTriggers: mutedTriggers ?? this.mutedTriggers,
  );
}

class SettingsNotifier extends Notifier<AppSettings> {
  SettingsNotifier(this._initial);

  static const storageKey = 'neml.settings';

  final AppSettings _initial;

  @override
  AppSettings build() => _initial;

  Future<void> update(AppSettings next) async {
    state = next;
    await ref
        .read(secureStorageProvider)
        .write(key: storageKey, value: jsonEncode(next.toJson()));
  }

  Future<void> toggleTrigger(String trigger, bool enabled) {
    final muted = {...state.mutedTriggers};
    enabled ? muted.remove(trigger) : muted.add(trigger);
    return update(state.copyWith(mutedTriggers: muted));
  }
}

/// Overridden in `main()` with the settings read from secure storage, so the
/// first frame already has the right server, theme and locale.
final settingsProvider = NotifierProvider<SettingsNotifier, AppSettings>(
  () => SettingsNotifier(const AppSettings()),
);

Future<AppSettings> loadSettings(TokenStore store) async {
  final raw = await store.readRaw(SettingsNotifier.storageKey);
  if (raw == null) return const AppSettings();
  try {
    return AppSettings.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  } on FormatException {
    return const AppSettings();
  }
}
