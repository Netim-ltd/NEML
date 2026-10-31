// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neml_mobile/core/network/online.dart';
import 'package:neml_mobile/shared/widgets.dart';

import '../helpers.dart';

void main() {
  group('offline behaviour (section 10.3)', () {
    testWidgets('banner shows the last update time while offline', (
      tester,
    ) async {
      await tester.pumpWidget(
        wrap(
          const OfflineBanner(),
          overrides: [offlineSince(DateTime(2026, 9, 15, 14, 5))],
        ),
      );
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('offline-banner')), findsOne);
      expect(find.text('çevrimdışı — son güncelleme 14:05'), findsOne);
    });

    testWidgets('banner is absent while online', (tester) async {
      await tester.pumpWidget(wrap(const OfflineBanner()));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('offline-banner')), findsNothing);
    });

    testWidgets('a blocked write says so; it is not queued', (tester) async {
      await tester.pumpWidget(
        wrap(
          Builder(
            builder: (context) => ElevatedButton(
              onPressed: () =>
                  reportWriteResult(context, const OfflineWriteBlocked()),
              child: const Text('yaz'),
            ),
          ),
        ),
      );
      await tester.tap(find.text('yaz'));
      await tester.pump();

      expect(
        find.textContaining('Yazma işlemleri engellendi'),
        findsOne,
        reason: 'section 10.3: offline writes are blocked, never queued',
      );
      expect(find.textContaining('kuyruğa alındı'), findsNothing);
    });

    testWidgets('a rejection is the one write that may be queued', (
      tester,
    ) async {
      await tester.pumpWidget(
        wrap(
          Builder(
            builder: (context) => ElevatedButton(
              onPressed: () =>
                  reportWriteResult(context, const OfflineRejectionQueued()),
              child: const Text('reddet'),
            ),
          ),
        ),
      );
      await tester.tap(find.text('reddet'));
      await tester.pump();

      expect(find.textContaining('ret kuyruğa alındı'), findsOne);
    });
  });
}
