// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth.dart';
import '../../core/config.dart';

/// Screen 1 of section 10.2 — e-mail/password, biometric lock, server address.
class LoginController extends AsyncNotifier<void> {
  @override
  void build() {}

  Future<void> submit(String email, String password) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(
      () => ref.read(authProvider.notifier).signIn(email.trim(), password),
    );
    final error = ref.read(authProvider).error;
    if (error != null) state = AsyncValue.error(error, StackTrace.current);
  }

  Future<void> setServer(String url) {
    final settings = ref.read(settingsProvider);
    return ref
        .read(settingsProvider.notifier)
        .update(settings.copyWith(serverUrl: url.trim()));
  }

  Future<void> setBiometricLock(bool enabled) {
    final settings = ref.read(settingsProvider);
    return ref
        .read(settingsProvider.notifier)
        .update(settings.copyWith(biometricLock: enabled));
  }
}

final loginControllerProvider = AsyncNotifierProvider<LoginController, void>(
  LoginController.new,
);
