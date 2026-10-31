// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neml_mobile/core/realtime/live_client.dart';
import 'package:neml_mobile/features/manufacturing/manufacturing_provider.dart';
import 'package:neml_mobile/features/manufacturing/manufacturing_view.dart';
import 'package:neml_mobile/l10n/app_localizations.dart';

import '../helpers.dart';

/// A queue with one printing job and one finished job whose slicer estimate
/// (section 6.4) is known, so the mass check has a nominal to work against.
Map<String, Object?> _routes() => {
  '/print-jobs': [
    {
      'jobId': 'PJ1',
      'state': 'printing',
      'printer_id': 'P1',
      'artifact': 'leg_link_v3',
      'est_time_h': 3.25,
      'est_filament_g': 48,
      'est_cost_try': 42.5,
    },
    {
      'id': 'PJ9',
      'state': 'done',
      'printerId': 'P1',
      'name': 'leg_link_v3',
      'estFilamentG': 48,
    },
  ],
  '/printers/P1/status': {
    'printerId': 'P1',
    'state': 'printing',
    'nozzleC': 214.5,
    'bedC': 59.8,
    'targetNozzleC': 215,
    'targetBedC': 60,
    'pct': 42.5,
    'layer': 88,
    'etaMin': 74,
    'jobName': 'leg_link_v3',
  },
};

void main() {
  late FakeHttp http;
  late AppLocalizations l10n;

  setUp(() => http = FakeHttp(routes: _routes()));
  setUpAll(() async {
    l10n = await AppLocalizations.delegate.load(const Locale('tr'));
  });

  // --- Thresholds, section 12.5 --------------------------------------------

  group('QC thresholds (section 12.5)', () {
    test('a caliper reading may use the Turkish decimal comma', () {
      expect(qcNumber('20,15'), 20.15);
      expect(qcNumber(' 20.15 '), 20.15);
      expect(qcNumber(''), isNull);
      expect(qcNumber('yok'), isNull);
    });

    test('a critical dimension is +/- 0.3 mm, boundary included', () {
      expect(qcPass(20.3, 20, kQcDimToleranceMm), isTrue, reason: 'boundary');
      expect(qcPass(19.7, 20, kQcDimToleranceMm), isTrue, reason: 'boundary');
      expect(qcPass(20.0, 20, kQcDimToleranceMm), isTrue);
      expect(qcPass(20.31, 20, kQcDimToleranceMm), isFalse);
      expect(qcPass(19.69, 20, kQcDimToleranceMm), isFalse);
    });

    test('mass is +/- 5% of the CAD estimate, boundary included', () {
      const nominal = 48.0;
      const tolerance = nominal * kQcMassToleranceRatio; // 2.4 g
      expect(qcPass(50.4, nominal, tolerance), isTrue, reason: 'boundary');
      expect(qcPass(45.6, nominal, tolerance), isTrue, reason: 'boundary');
      expect(qcPass(50.41, nominal, tolerance), isFalse);
      expect(qcPass(45.59, nominal, tolerance), isFalse);
    });

    test('warp is a magnitude, <= 0.5 mm', () {
      expect(qcPass(0.5, 0, kQcWarpLimitMm), isTrue, reason: 'boundary');
      expect(qcPass(-0.5, 0, kQcWarpLimitMm), isTrue);
      expect(qcPass(0.51, 0, kQcWarpLimitMm), isFalse);
      expect(qcPass(0, 0, kQcWarpLimitMm), isTrue);
    });

    test('no measurement and no nominal both mean no verdict, never a fail', () {
      expect(qcPass(null, 20, kQcDimToleranceMm), isNull);
      expect(qcPass(20, null, kQcDimToleranceMm), isNull);
      expect(qcPass(20, 20, null), isNull);
    });
  });

  // --- The form as the operator types it ------------------------------------

  group('QC form (section 10.2 screen 11)', () {
    /// Opens the sheet for the finished job.
    Future<void> openForm(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1000, 3000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        wrap(const ManufacturingView(), overrides: apiOverrides(http)),
      );
      await settle(tester);
      await tester.tap(find.byKey(const Key('qc-PJ9')));
      await settle(tester);
    }

    /// The pass/fail label currently shown next to a field, or `null` when the
    /// field has not been given enough to judge.
    String? verdict(WidgetTester tester, String id) {
      final found = find.byKey(Key('qc-$id-verdict'));
      return found.evaluate().isEmpty ? null : tester.widget<Text>(found).data;
    }

    Future<void> type(WidgetTester tester, String id, String text) async {
      await tester.enterText(find.byKey(Key('qc-$id')), text);
      await tester.pump();
    }

    testWidgets('a dimension is judged on every keystroke, not on submit', (
      tester,
    ) async {
      await openForm(tester);

      // Nothing to compare against yet.
      expect(verdict(tester, 'dim-0'), isNull);
      await type(tester, 'dim-0-cad', '20');
      expect(verdict(tester, 'dim-0'), isNull);

      // Inside tolerance, exactly on the boundary.
      await type(tester, 'dim-0', '20,3');
      expect(verdict(tester, 'dim-0'), l10n.pass);

      // One hundredth further out and the operator sees it immediately.
      await type(tester, 'dim-0', '20.31');
      expect(verdict(tester, 'dim-0'), l10n.fail);

      // And back in.
      await type(tester, 'dim-0', '19.7');
      expect(verdict(tester, 'dim-0'), l10n.pass);
    });

    testWidgets('mass is judged against the slicer estimate on the job', (
      tester,
    ) async {
      await openForm(tester);
      // 48 g estimate -> +/- 2.4 g.
      expect(find.textContaining('48.0 g'), findsOneWidget);

      await type(tester, 'mass', '50.4');
      expect(verdict(tester, 'mass'), l10n.pass);
      await type(tester, 'mass', '50.41');
      expect(verdict(tester, 'mass'), l10n.fail);
    });

    testWidgets('warp is judged against the 0.5 mm limit', (tester) async {
      await openForm(tester);
      await type(tester, 'warp', '0.5');
      expect(verdict(tester, 'warp'), l10n.pass);
      await type(tester, 'warp', '0.6');
      expect(verdict(tester, 'warp'), l10n.fail);
    });

    testWidgets('the part verdict appears once every measurement is in', (
      tester,
    ) async {
      await openForm(tester);
      final submit = find.byKey(const Key('qc-submit'));
      expect(
        tester.widget<FilledButton>(submit).onPressed,
        isNull,
        reason: 'an empty form has nothing to record',
      );
      expect(find.byKey(const Key('qc-verdict')), findsNothing);

      for (var i = 0; i < 3; i++) {
        await type(tester, 'dim-$i-cad', '20');
        await type(tester, 'dim-$i', '20.1');
      }
      await type(tester, 'mass', '47.5');
      await type(tester, 'warp', '0.2');

      expect(tester.widget<FilledButton>(submit).onPressed, isNotNull);
      expect(
        tester.widget<Text>(find.byKey(const Key('qc-verdict'))).data,
        contains(l10n.pass),
      );

      // A failed pin gauge alone scraps the part (section 12.5).
      await tester.tap(find.byKey(const Key('qc-hole')));
      await tester.pump();
      expect(
        tester.widget<Text>(find.byKey(const Key('qc-verdict'))).data,
        contains(l10n.fail),
      );
    });

    testWidgets('submitting posts the measurements and their nominals', (
      tester,
    ) async {
      await openForm(tester);

      for (var i = 0; i < 3; i++) {
        await type(tester, 'dim-$i-cad', '20');
        await type(tester, 'dim-$i', '19.85');
      }
      await type(tester, 'mass', '47,5');
      await type(tester, 'warp', '0.2');
      await tester.tap(find.byKey(const Key('qc-adhesion')));
      await tester.pump();

      await tester.tap(find.byKey(const Key('qc-submit')));
      await settle(tester);

      final posted =
          http.sent.lastWhere((r) => r.path == '/print-jobs/PJ9/qc').data!
              as Map;
      expect(posted['dim_1_mm'], 19.85);
      expect(posted['dim_3_mm'], 19.85);
      // Section 12.5 chases systematic deviation across three parts, which
      // needs the direction of the error, so the nominal travels with it.
      expect(posted['dim_1_nominal_mm'], 20);
      expect(posted['mass_g'], 47.5, reason: 'comma decimal separator');
      expect(posted['mass_nominal_g'], 48);
      expect(posted['warp_mm'], 0.2);
      expect(posted['hole_gauge_ok'], isTrue);
      expect(posted['layer_adhesion_ok'], isFalse);
    });
  });

  // --- Live printer status, section 9.4 PrintProgress -----------------------

  group('live printer status (T-095)', () {
    testWidgets('the card shows temperatures, layer, ETA and progress', (
      tester,
    ) async {
      await tester.pumpWidget(
        wrap(const ManufacturingView(), overrides: apiOverrides(http)),
      );
      await settle(tester);

      expect(find.text('215 / 215 C'), findsOneWidget);
      expect(find.text('60 / 60 C'), findsOneWidget);
      expect(find.text('88'), findsOneWidget);
      expect(find.text('74 min'), findsOneWidget);
      expect(find.text('43%'), findsOneWidget);
      expect(
        tester
            .widget<LinearProgressIndicator>(
              find.byKey(const Key('print-progress')),
            )
            .value,
        closeTo(0.425, 1e-9),
      );
    });

    test('a PrintProgress event moves the card without a refetch', () async {
      final events = StreamController<LiveEvent>.broadcast();
      addTearDown(events.close);
      final container = ProviderContainer(
        overrides: [
          ...apiOverrides(http),
          liveEventsProvider.overrideWith((ref) => events.stream),
        ],
      );
      addTearDown(container.dispose);
      // Providers are auto-disposed when nothing listens, and a disposed
      // notifier is not subscribed to the hub.
      container.listen(manufacturingProvider, (_, _) {});

      final before = await container.read(manufacturingProvider.future);
      expect(before.printer!.pct, 42.5);
      http.sent.clear();

      events.add(
        const LiveEvent('PrintProgress', {
          'jobId': 'PJ1',
          'pct': 63.5,
          'layer': 120,
          'etaMin': 31,
          'nozzleC': 215.1,
          'bedC': 60.2,
        }),
      );
      await Future<void>.delayed(const Duration(milliseconds: 20));

      final after = container.read(manufacturingProvider).value!.printer!;
      expect(after.pct, 63.5);
      expect(after.layer, 120);
      expect(after.etaMin, 31);
      expect(after.nozzleC, 215.1);
      expect(after.bedC, 60.2);
      // Targets are not in the event payload and must survive it.
      expect(after.targetNozzleC, 215);
      expect(http.sent, isEmpty, reason: '1 Hz polling would be a bug');
    });
  });
}
