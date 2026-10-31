// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config.dart';
import '../db/cache_db.dart';
import '../models.dart';
import '../network/api.dart';
import 'token_store.dart';

/// Holds the signed-in [Session] (section 5.5). `null` means signed out.
///
/// Cold start reads the keychain; with the biometric lock on, that read is the
/// prompt the operator sees before any lab data is decrypted.
class AuthNotifier extends AsyncNotifier<Session?> {
  @override
  Future<Session?> build() async {
    final biometric = ref.read(settingsProvider).biometricLock;
    try {
      return await ref.read(tokenStoreProvider).read(biometric: biometric);
    } on Object {
      // Biometric prompt cancelled or keystore unavailable: stay signed out.
      return null;
    }
  }

  Future<void> signIn(String email, String password) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      final session = await ref.read(apiProvider).login(email, password);
      await _persist(session);
      return session;
    });
  }

  /// Called by [AuthInterceptor] after a successful refresh-token rotation.
  void applyRefreshed(Session session) {
    state = AsyncValue.data(session);
    _persist(session);
  }

  void signOut() {
    state = const AsyncValue.data(null);
    final api = ref.read(apiProvider);
    // Best effort: the local session is gone either way.
    api.logout().ignore();
    ref.read(tokenStoreProvider).clear();
    ref.read(cacheDbProvider).wipe();
  }

  Future<void> _persist(Session session) => ref
      .read(tokenStoreProvider)
      .save(session, biometric: ref.read(settingsProvider).biometricLock);
}

final authProvider = AsyncNotifierProvider<AuthNotifier, Session?>(
  AuthNotifier.new,
);

/// Convenience for widgets that only need the role checks of section 5.5.
final sessionProvider = Provider<Session?>(
  (ref) => ref.watch(authProvider).value,
);
