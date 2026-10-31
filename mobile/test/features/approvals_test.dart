// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'dart:async';

import 'package:dio/dio.dart';
import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:neml_mobile/core/auth/auth.dart';
import 'package:neml_mobile/core/db/cache_db.dart';
import 'package:neml_mobile/core/models.dart';
import 'package:neml_mobile/core/network/api.dart';
import 'package:neml_mobile/core/network/dio_client.dart';
import 'package:neml_mobile/core/network/interceptors.dart';
import 'package:neml_mobile/core/network/online.dart';
import 'package:neml_mobile/core/realtime/live_client.dart';
import 'package:neml_mobile/features/approvals/approvals_provider.dart';
import 'package:neml_mobile/features/approvals/approvals_view.dart';
import 'package:neml_mobile/l10n/app_localizations.dart';

import '../helpers.dart';

String _iso(Duration fromNow) =>
    DateTime.now().toUtc().add(fromNow).toIso8601String();

/// One live level-4 request and one whose section 5.2 window has closed.
Map<String, Object?> _routes() => {
  '/approvals': [
    {
      'id': 'A1',
      'level': 4,
      'subject_kind': 'print_job',
      'subject_id': 'PJ1',
      'subject': 'Bacak baglantisi v3 baski',
      'expires_at': _iso(const Duration(hours: 4)),
    },
    {
      'id': 'A9',
      'level': 3,
      'subjectKind': 'deployment',
      'subjectId': 'G2',
      'subject': 'Serbest calisma',
      'expiresAt': _iso(const Duration(hours: -1)),
    },
  ],
  '/approvals/A1': {
    'id': 'A1',
    'level': 4,
    'subjectKind': 'print_job',
    'subjectId': 'PJ1',
    'subject': 'Bacak baglantisi v3 baski',
    'expiresAt': _iso(const Duration(hours: 4)),
    'costTry': 42.5,
    'estTimeH': 3.25,
  },
  '/approvals/A9': {
    'id': 'A9',
    'level': 3,
    'subjectKind': 'deployment',
    'subjectId': 'G2',
    'subject': 'Serbest calisma',
    'expiresAt': _iso(const Duration(hours: -1)),
  },
};

const _owner = Session(
  access: 'a',
  refresh: 'r',
  email: 'owner@neml',
  role: 'owner',
);

/// The API the screen really talks to, with the section 10.3 write guard in
/// the chain and the link down. Nothing else about it is faked: whether a
/// write is blocked or queued is decided by [NemlApi] and
/// [WriteGuardInterceptor] exactly as it is in the app.
NemlApi offlineApi(FakeHttp http, CacheDb db) => NemlApi(
  Dio(BaseOptions(baseUrl: 'https://neml.test$kApiPrefix'))
    ..httpClientAdapter = http
    ..interceptors.add(
      WriteGuardInterceptor(
        isOnline: () => false,
        queueRejection: (options) => db.queueRejection(
          options.path.split('/')[2],
          '${(options.data as Map)['note']}',
        ),
      ),
    ),
);

void main() {
  late FakeHttp http;
  late AppLocalizations l10n;

  setUp(() => http = FakeHttp(routes: _routes()));
  setUpAll(() async {
    l10n = await AppLocalizations.delegate.load(const Locale('tr'));
  });

  // --- Expiry, section 5.2 --------------------------------------------------

  group('approval expiry (section 5.2)', () {
    final at = DateTime(2026, 9, 15, 12);

    test('the boundary counts as expired', () {
      expect(approvalExpired(at, at.subtract(const Duration(seconds: 1))), isFalse);
      expect(approvalExpired(at, at), isTrue, reason: 'no window left');
      expect(approvalExpired(at, at.add(const Duration(seconds: 1))), isTrue);
    });

    test('no expiry at all is not an expiry', () {
      expect(approvalExpired(null, at), isFalse);
    });

    test('the documented default window is 24 h', () {
      expect(kApprovalTimeout, const Duration(hours: 24));
    });

    testWidgets('the countdown disables approval the moment it reaches zero', (
      tester,
    ) async {
      await tester.pumpWidget(
        wrap(
          ApprovalDecisionPanel(
            level: 3,
            expiresAt: DateTime.now().add(const Duration(seconds: 3)),
            onApprove: (_) async {},
            onReject: (_) async {},
          ),
          overrides: [sessionProvider.overrideWithValue(_owner)],
        ),
      );
      await settle(tester);

      final approve = find.byKey(const Key('approval-approve'));
      expect(tester.widget<FilledButton>(approve).onPressed, isNotNull);
      expect(find.byKey(const Key('approval-expired')), findsNothing);

      // The countdown reads the wall clock, so real time has to move; the pump
      // then fires the 1 Hz ticker that notices.
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(seconds: 3, milliseconds: 200)),
      );
      await tester.pump(const Duration(seconds: 1));

      expect(
        tester.widget<FilledButton>(approve).onPressed,
        isNull,
        reason: 'section 5.2: an expired request is auto-rejected server side',
      );
      expect(find.byKey(const Key('approval-expired')), findsOneWidget);
      // Rejecting still works: it errs in the safe direction.
      expect(
        tester
            .widget<OutlinedButton>(find.byKey(const Key('approval-reject')))
            .onPressed,
        isNotNull,
      );
    });

    testWidgets('the pending list marks an expired request', (tester) async {
      await tester.pumpWidget(
        wrap(const ApprovalsView(), overrides: apiOverrides(http)),
      );
      await settle(tester);

      expect(find.byKey(const Key('approval-A1')), findsOneWidget);
      expect(find.byKey(const Key('approval-A9')), findsOneWidget);
      expect(find.textContaining(l10n.expired), findsOneWidget);
      expect(find.byIcon(Icons.block), findsOneWidget);
    });

    testWidgets('an expired request cannot be approved from the detail', (
      tester,
    ) async {
      await tester.pumpWidget(
        wrap(
          const ApprovalDetailView(approvalId: 'A9'),
          overrides: apiOverrides(http),
        ),
      );
      await settle(tester);

      expect(
        tester
            .widget<FilledButton>(find.byKey(const Key('approval-approve')))
            .onPressed,
        isNull,
      );
      expect(find.byKey(const Key('approval-expired')), findsOneWidget);
    });
  });

  // --- Level 4 typed confirmation, section 10.2 screen 10 -------------------

  group('level 4 typed confirmation', () {
    test('near misses are refused, whitespace included', () {
      for (final typed in [
        'onayliyorum',
        'onaylıyorum',
        'ONAYLIYORUZ',
        'ONAYLIYORU',
        'ONAYLIYORUMM',
        'ONAYLIYORUM!',
        'ONAYLI YORUM',
        // Section 10.2 screen 10 says the operator types "ONAYLIYORUM". A
        // keyboard that appends a space has typed something else, and a
        // level 4 gate does not round in the operator's favour.
        'ONAYLIYORUM ',
        ' ONAYLIYORUM',
        '\tONAYLIYORUM\n',
        '',
      ]) {
        expect(
          level4ConfirmationOk(4, typed),
          isFalse,
          reason: 'accepted "$typed"',
        );
      }
    });

    test('only the word itself passes, and only at level 4', () {
      expect(level4ConfirmationOk(4, kLevel4ConfirmWord), isTrue);
      expect(kLevel4ConfirmWord, 'ONAYLIYORUM');
      for (final level in [1, 2, 3]) {
        expect(level4ConfirmationOk(level, ''), isTrue);
      }
    });

    testWidgets('the detail screen refuses the near misses too', (
      tester,
    ) async {
      await tester.pumpWidget(
        wrap(
          const ApprovalDetailView(approvalId: 'A1'),
          overrides: apiOverrides(http),
        ),
      );
      await settle(tester);

      final approve = find.byKey(const Key('approval-approve'));
      final field = find.byKey(const Key('level4-confirm'));
      for (final typed in ['onayliyorum', 'ONAYLIYORUZ', 'ONAYLIYORUM ']) {
        await tester.enterText(field, typed);
        await tester.pump();
        expect(
          tester.widget<FilledButton>(approve).onPressed,
          isNull,
          reason: 'accepted "$typed"',
        );
        // A trailing space is invisible; the field has to say why it refused.
        expect(
          tester.widget<TextField>(field).decoration!.errorText,
          isNotNull,
          reason: 'silent refusal of "$typed"',
        );
      }

      await tester.enterText(
        find.byKey(const Key('level4-confirm')),
        kLevel4ConfirmWord,
      );
      await tester.pump();
      expect(tester.widget<FilledButton>(approve).onPressed, isNotNull);
    });
  });

  // --- Offline asymmetry, section 10.3 --------------------------------------

  group('offline asymmetry on screen 10 (section 10.3)', () {
    late CacheDb db;
    late NemlApi api;

    setUp(() {
      db = CacheDb(NativeDatabase.memory());
      api = offlineApi(http, db);
    });
    tearDown(() => db.close());

    List<Override> overrides() => [
      apiProvider.overrideWithValue(api),
      authProvider.overrideWith(() => FakeAuth(_owner)),
      liveClientProvider.overrideWithValue(null),
      offlineSince(DateTime(2026, 9, 15, 14, 5)),
    ];

    test('approving offline is blocked and leaves nothing queued', () async {
      final container = ProviderContainer(overrides: overrides());
      addTearDown(container.dispose);
      await container.read(approvalsProvider.future);
      http.sent.clear();

      await expectLater(
        container.read(approvalsProvider.notifier).approve('A1', 'tamam'),
        throwsA(
          isA<DioException>().having(
            (e) => e.error,
            'error',
            isA<OfflineWriteBlocked>(),
          ),
        ),
      );
      expect(http.sent, isEmpty, reason: 'it must not reach the wire either');
      expect(await db.pendingRejections(), isEmpty);
    });

    test('rejecting offline is queued instead', () async {
      final container = ProviderContainer(overrides: overrides());
      addTearDown(container.dispose);
      await container.read(approvalsProvider.future);
      http.sent.clear();

      await expectLater(
        container.read(approvalsProvider.notifier).reject('A1', 'guvenli degil'),
        throwsA(
          isA<DioException>().having(
            (e) => e.error,
            'error',
            isA<OfflineRejectionQueued>(),
          ),
        ),
      );
      expect(http.sent, isEmpty);
      final queued = await db.pendingRejections();
      expect(queued.single.approvalId, 'A1');
      expect(queued.single.note, 'guvenli degil');
    });

    /// Opens the level-4 detail with the confirmation word already typed, so
    /// either button is one tap away.
    Future<void> openDetail(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1000, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);

      await tester.pumpWidget(
        wrap(const ApprovalDetailView(approvalId: 'A1'), overrides: overrides()),
      );
      await settle(tester);
      await tester.enterText(
        find.byKey(const Key('level4-confirm')),
        kLevel4ConfirmWord,
      );
      await tester.pump();
    }

    testWidgets('the screen says the approval was blocked, not parked', (
      tester,
    ) async {
      await openDetail(tester);
      await tester.tap(find.byKey(const Key('approval-approve')));
      await settle(tester);

      expect(find.textContaining('Yazma işlemleri engellendi'), findsOneWidget);
      expect(find.textContaining('kuyruğa alındı'), findsNothing);
      expect(await db.pendingRejections(), isEmpty);
    });

    testWidgets('the screen says the rejection was parked', (tester) async {
      await openDetail(tester);
      await tester.tap(find.byKey(const Key('approval-reject')));
      await settle(tester);

      expect(find.textContaining('ret kuyruğa alındı'), findsOneWidget);
      expect((await db.pendingRejections()).single.approvalId, 'A1');
    });
  });

  // --- The other half of the asymmetry: a parked rejection must leave ------

  group('queued rejections are replayed (section 10.3)', () {
    late CacheDb db;

    setUp(() => db = CacheDb(NativeDatabase.memory()));
    tearDown(() => db.close());

    /// A container that starts offline with two rejections already parked.
    Future<ProviderContainer> parked(FakeHttp http) async {
      await db.queueRejection('A1', 'guvenli degil');
      await db.queueRejection('A9', 'suresi gecti');
      final container = ProviderContainer(
        overrides: [
          apiProvider.overrideWithValue(fakeApi(http)),
          cacheDbProvider.overrideWithValue(db),
          authProvider.overrideWith(() => FakeAuth(_owner)),
          liveClientProvider.overrideWithValue(null),
          offlineSince(DateTime(2026, 9, 15, 14, 5)),
        ],
      );
      addTearDown(container.dispose);
      container.listen(rejectionFlusherProvider, (_, _) {});
      return container;
    }

    test('coming back online sends them and clears the queue', () async {
      final http = FakeHttp(routes: _routes());
      final container = await parked(http);

      container.read(onlineProvider.notifier).markOnline();
      await Future<void>.delayed(const Duration(milliseconds: 50));

      expect(
        http.sent.map((r) => r.path),
        containsAll(['/approvals/A1/reject', '/approvals/A9/reject']),
      );
      expect(
        await db.pendingRejections(),
        isEmpty,
        reason: 'a parked rejection that is never sent is not fail-safe',
      );
    });

    test('a rejection the server refuses stays parked for the next try', () async {
      final http = FakeHttp(routes: _routes(), status: 503);
      final container = await parked(http);

      container.read(onlineProvider.notifier).markOnline();
      await Future<void>.delayed(const Duration(milliseconds: 50));

      expect((await db.pendingRejections()).length, 2);
    });

    test('a flap that never went offline replays nothing', () async {
      final http = FakeHttp(routes: _routes());
      final container = await parked(http);

      // markOnline from online is a no-op transition; replaying on every tick
      // would post the same rejection over and over.
      container.read(onlineProvider.notifier).markOffline();
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(http.sent, isEmpty);
      expect((await db.pendingRejections()).length, 2);
    });
  });

  // --- Liveness, section 9.4 ApprovalRequested ------------------------------

  test('an ApprovalRequested event re-reads the pending list', () async {
    final http = FakeHttp(routes: _routes());
    final events = StreamController<LiveEvent>.broadcast();
    addTearDown(events.close);
    final container = ProviderContainer(
      overrides: [
        ...apiOverrides(http),
        liveEventsProvider.overrideWith((ref) => events.stream),
      ],
    );
    addTearDown(container.dispose);
    container.listen(approvalsProvider, (_, _) {});
    await container.read(approvalsProvider.future);
    http.sent.clear();

    events.add(const LiveEvent('TelemetryTick', {'robotId': 'R01'}));
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(http.sent, isEmpty, reason: 'not every event concerns screen 10');

    events.add(
      const LiveEvent('ApprovalRequested', {'approvalId': 'A2', 'level': 4}),
    );
    await Future<void>.delayed(const Duration(milliseconds: 20));
    await container.read(approvalsProvider.future);
    expect(http.sent.map((r) => r.path), contains('/approvals'));
  });
}
