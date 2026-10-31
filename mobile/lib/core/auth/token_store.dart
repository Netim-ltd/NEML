// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../models.dart';

/// Keychain / Keystore backed storage for the JWT pair of section 5.5.
///
/// When the biometric lock is on, the session is written behind a
/// user-presence constraint, so reading it at cold start makes the platform
/// prompt for Face ID / fingerprint. That is the whole biometric lock: no
/// extra plugin, no in-app passcode of our own.
class TokenStore {
  TokenStore(this._storage);

  static const sessionKey = 'neml.session';

  final FlutterSecureStorage _storage;

  static const _androidBiometric = AndroidOptions.biometric(
    enforceBiometrics: true,
    biometricPromptTitle: 'NEML',
    biometricPromptSubtitle: 'Oturumu acmak icin kimliginizi dogrulayin',
  );
  static const _appleBiometric = IOSOptions(
    accessControlFlags: [AccessControlFlag.userPresence],
  );

  Future<Session?> read({required bool biometric}) async {
    final raw = await _storage.read(
      key: sessionKey,
      aOptions: biometric ? _androidBiometric : null,
      iOptions: biometric ? _appleBiometric : null,
      mOptions: biometric ? _appleBiometric : null,
    );
    if (raw == null) return null;
    try {
      return Session.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } on FormatException {
      return null;
    }
  }

  Future<void> save(Session session, {required bool biometric}) =>
      _storage.write(
        key: sessionKey,
        value: jsonEncode(session.toJson()),
        aOptions: biometric ? _androidBiometric : null,
        iOptions: biometric ? _appleBiometric : null,
        mOptions: biometric ? _appleBiometric : null,
      );

  Future<void> clear() => _storage.delete(key: sessionKey);

  /// Plain read used for non-secret preferences (section 13 settings blob).
  Future<String?> readRaw(String key) => _storage.read(key: key);
}

final secureStorageProvider = Provider<FlutterSecureStorage>(
  (ref) => const FlutterSecureStorage(),
);

final tokenStoreProvider = Provider<TokenStore>(
  (ref) => TokenStore(ref.watch(secureStorageProvider)),
);
