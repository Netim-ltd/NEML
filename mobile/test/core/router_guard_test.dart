// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neml_mobile/core/models.dart';
import 'package:neml_mobile/core/router/router.dart';

const _session = Session(
  access: 'a',
  refresh: 'r',
  email: 'mg@neml',
  role: 'owner',
);

void main() {
  group('authRedirect', () {
    test('signed out is pushed to the login screen', () {
      expect(
        authRedirect(auth: const AsyncValue.data(null), location: '/'),
        loginRoute,
      );
      expect(
        authRedirect(
          auth: const AsyncValue.data(null),
          location: '/approvals/42',
        ),
        loginRoute,
      );
    });

    test('signed out already on login stays put', () {
      expect(
        authRedirect(auth: const AsyncValue.data(null), location: loginRoute),
        isNull,
      );
    });

    test('signed in is bounced off the login screen', () {
      expect(
        authRedirect(
          auth: const AsyncValue.data(_session),
          location: loginRoute,
        ),
        '/',
      );
    });

    test('signed in keeps the requested route', () {
      expect(
        authRedirect(
          auth: const AsyncValue.data(_session),
          location: '/robots/R01',
        ),
        isNull,
      );
    });

    test('while the keychain read is pending nothing is redirected', () {
      // With the biometric lock on this is the OS prompt; bouncing the
      // operator to /login mid-prompt would drop the session.
      expect(
        authRedirect(auth: const AsyncValue.loading(), location: '/'),
        isNull,
      );
      expect(
        authRedirect(auth: const AsyncValue.loading(), location: loginRoute),
        isNull,
      );
    });

    test('a failed session read is treated as signed out', () {
      final failed = AsyncValue<Session?>.error('keystore', StackTrace.empty);
      expect(authRedirect(auth: failed, location: '/'), loginRoute);
    });
  });
}
