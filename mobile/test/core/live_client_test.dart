// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neml_mobile/core/auth/auth.dart';
import 'package:neml_mobile/core/config.dart';
import 'package:neml_mobile/core/realtime/live_client.dart';

import '../helpers.dart';

/// The SignalR client of NEML_SPEC.md section 9.4. Nothing here talks to a
/// real hub: port 1 is always refused, which is the "hub is down" path.
const _deadHub = 'http://127.0.0.1:1';

LiveClient deadClient({void Function()? onDisconnected}) => LiveClient(
  serverUrl: _deadHub,
  accessToken: () async => testSession.access,
  onDisconnected: onDisconnected,
);

void main() {
  test('every server-to-client event of section 9.4 is subscribed', () {
    expect(kLiveEvents, const [
      'RobotState',
      'TelemetryTick',
      'TaskUpdated',
      'TaskRunEvent',
      'CampaignProgress',
      'ApprovalRequested',
      'ApprovalDecided',
      'PrintProgress',
      'BrainStatus',
      'Alert',
    ]);
  });

  test('a fresh client is not connected and subscribes to nothing', () async {
    final client = deadClient();
    expect(client.connected, isFalse);

    // Before the hub is up these are no-ops rather than errors: a screen may
    // ask for its group while the link is still coming back.
    await client.subscribeRobot('R01');
    await client.subscribeCampaign('C1');
    await client.unsubscribeAll();

    await client.dispose();
  });

  test('a dead hub surfaces the failure instead of pretending to be live',
      () async {
    final client = deadClient();
    await expectLater(client.start(), throwsA(anything));
    expect(client.connected, isFalse);
    expect(client.events, isNotNull);
  });

  test('a LiveEvent carries the hub method name and its payload', () {
    const event = LiveEvent('Alert', {'severity': 'critical', 'code': 'E-42'});
    expect(event.name, 'Alert');
    expect(event.data['severity'], 'critical');
  });

  group('providers', () {
    ProviderContainer containerFor(bool signedIn) {
      final c = ProviderContainer(
        overrides: [
          authProvider.overrideWith(
            () => FakeAuth(signedIn ? testSession : null),
          ),
          settingsProvider.overrideWith(
            () => SettingsNotifier(const AppSettings(serverUrl: _deadHub)),
          ),
        ],
      );
      addTearDown(c.dispose);
      return c;
    }

    test('signed out there is no hub connection at all', () async {
      final container = containerFor(false);
      await container.read(authProvider.future);
      expect(container.read(liveClientProvider), isNull);
      // Both hub streams stay empty, so nothing ever dials the server.
      expect(container.read(liveEventsProvider), isA<AsyncLoading<LiveEvent>>());
      expect(
        container.read(liveEventProvider('Alert')),
        isA<AsyncLoading<LiveEvent>>(),
      );
    });

    test('signed in the client points at the operator server', () async {
      final container = containerFor(true);
      await container.read(authProvider.future);
      final client = container.read(liveClientProvider);
      expect(client, isNotNull);
      expect(client!.serverUrl, _deadHub);
      expect(await client.accessToken(), testSession.access);
    });
  });
}
