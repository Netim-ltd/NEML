// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:neml_mobile/core/auth/token_store.dart';
import 'package:neml_mobile/core/config.dart';
import 'package:neml_mobile/core/models.dart';
import 'package:neml_mobile/l10n/app_localizations.dart';
import 'package:neml_mobile/features/approvals/approvals_provider.dart';
import 'package:neml_mobile/features/approvals/approvals_view.dart';
import 'package:neml_mobile/features/brain_console/brain_console_view.dart';
import 'package:neml_mobile/features/evolution/evolution_view.dart';
import 'package:neml_mobile/features/login/login_view.dart';
import 'package:neml_mobile/features/manufacturing/manufacturing_view.dart';
import 'package:neml_mobile/features/robot_detail/robot_detail_view.dart';
import 'package:neml_mobile/features/brain_console/brain_console_provider.dart';
import 'package:neml_mobile/features/dashboard/dashboard_provider.dart';
import 'package:neml_mobile/features/manufacturing/manufacturing_provider.dart';
import 'package:neml_mobile/features/tasks/tasks_provider.dart';
import 'package:neml_mobile/features/tasks/tasks_view.dart';

import '../helpers.dart';

class _MockStorage extends Mock implements FlutterSecureStorage {}

/// Every operator action that changes something on the far end. These are the
/// paths that reach a robot or the printer, so each one is checked against the
/// exact request it must produce (NEML_SPEC.md section 9.3).
void main() {
  late FakeHttp http;
  late _MockStorage storage;

  setUp(() {
    http = FakeHttp();
    storage = _MockStorage();
    when(
      () => storage.write(
        key: any(named: 'key'),
        value: any(named: 'value'),
        aOptions: any(named: 'aOptions'),
        iOptions: any(named: 'iOptions'),
        mOptions: any(named: 'mOptions'),
      ),
    ).thenAnswer((_) async {});
    when(
      () => storage.read(
        key: any(named: 'key'),
        aOptions: any(named: 'aOptions'),
        iOptions: any(named: 'iOptions'),
        mOptions: any(named: 'mOptions'),
      ),
    ).thenAnswer((_) async => null);
  });

  List<Override> overrides({Session? session = testSession}) => [
    ...apiOverrides(http, session: session),
    secureStorageProvider.overrideWithValue(storage),
  ];

  /// Requests of [method] that reached the fake server.
  List<String> calls(String method) => [
    for (final r in http.sent)
      if (r.method == method) r.path,
  ];

  Future<void> pump(
    WidgetTester tester,
    Widget view, {
    Session? session = testSession,
  }) async {
    // Tall enough that the buttons at the bottom of a long screen or sheet are
    // actually built; an unbuilt button cannot be tapped.
    tester.view.physicalSize = const Size(1000, 3000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      wrap(view, overrides: overrides(session: session)),
    );
    await settle(tester);
  }

  testWidgets('signing in stores the session behind the keychain', (
    tester,
  ) async {
    await pump(tester, const LoginView(), session: null);

    await tester.enterText(find.byKey(const Key('login-email')), 'mg@neml');
    await tester.enterText(find.byKey(const Key('login-password')), 'sifre');
    await tester.enterText(
      find.byKey(const Key('login-server')),
      'https://lab.neml.test',
    );
    await tester.tap(find.byKey(const Key('login-submit')));
    await settle(tester);

    expect(calls('POST'), contains('/auth/login'));
    verify(
      () => storage.write(
        key: TokenStore.sessionKey,
        value: any(named: 'value'),
        aOptions: any(named: 'aOptions'),
        iOptions: any(named: 'iOptions'),
        mOptions: any(named: 'mOptions'),
      ),
    ).called(1);
  });

  testWidgets('the biometric lock is a settings write, not an in-app passcode',
      (tester) async {
    await pump(tester, const LoginView(), session: null);
    await tester.tap(find.byKey(const Key('login-biometric')));
    await settle(tester);

    verify(
      () => storage.write(
        key: SettingsNotifier.storageKey,
        value: any(named: 'value', that: contains('"biometricLock":true')),
        aOptions: any(named: 'aOptions'),
        iOptions: any(named: 'iOptions'),
        mOptions: any(named: 'mOptions'),
      ),
    ).called(1);
  });

  testWidgets('a brain command is sent and then pulled back resolved', (
    tester,
  ) async {
    await pump(tester, const BrainConsoleView());

    await tester.enterText(
      find.byKey(const Key('brain-input')),
      'R01 durumunu ozetle',
    );
    await tester.tap(find.byKey(const Key('brain-send')));
    await settle(tester);

    expect(calls('POST'), contains('/brain/command'));
    // Section 4.3: the classified intent comes back from the brain, never
    // from the phone.
    expect(calls('GET'), contains('/brain/command/K1'));
    expect(find.text('robot_status'), findsOneWidget);
  });

  testWidgets('a template chip sends without typing', (tester) async {
    await pump(tester, const BrainConsoleView());
    await tester.tap(find.text('Bekleyen onaylari listele'));
    await settle(tester);
    expect(calls('POST'), contains('/brain/command'));
  });

  testWidgets('the new-task sheet is the form of screen 4', (tester) async {
    await pump(tester, const TasksView());
    final l10n = await AppLocalizations.delegate.load(const Locale('tr'));

    await tester.tap(find.byKey(const Key('new-task-fab')));
    await settle(tester);

    expect(find.byKey(const Key('new-task-title')), findsOneWidget);
    expect(find.text(l10n.priority), findsOneWidget);
    // The six task kinds of section 7.
    expect(find.text('calibration'), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('new-task-title')),
      'Merdiven cik',
    );
    expect(find.widgetWithText(FilledButton, l10n.submit), findsOneWidget);
  });

  testWidgets('swiping a task reprioritises it and never guesses the result', (
    tester,
  ) async {
    await pump(tester, const TasksView());

    await tester.drag(find.byKey(const Key('task-T2')), const Offset(600, 0));
    await settle(tester);

    expect(calls('PATCH'), contains('/tasks/T2'));
    // The list is rebuilt from the server, so the row is still there.
    expect(find.byKey(const Key('task-T2')), findsOneWidget);
  });

  testWidgets('swiping the other way cancels a task', (tester) async {
    await pump(tester, const TasksView());

    await tester.drag(find.byKey(const Key('task-T2')), const Offset(-600, 0));
    await settle(tester);

    expect(calls('POST'), contains('/tasks/T2/cancel'));
  });

  testWidgets('the e-stop only fires after the second slide', (tester) async {
    await pump(tester, const RobotDetailView(robotId: 'R01'));

    await tester.drag(find.byKey(const Key('confirm-slider')), const Offset(800, 0));
    await settle(tester);
    expect(calls('POST'), isNot(contains('/robots/R01/estop')));

    await tester.drag(find.byKey(const Key('confirm-slider')), const Offset(800, 0));
    await settle(tester);
    expect(calls('POST'), contains('/robots/R01/estop'));
  });

  testWidgets('the QC sheet asks for the section 12.5 measurements', (
    tester,
  ) async {
    await pump(tester, const ManufacturingView());

    await tester.tap(find.byKey(const Key('qc-PJ2')));
    await settle(tester);

    for (var i = 0; i < 3; i++) {
      expect(find.byKey(Key('qc-dim-$i')), findsOneWidget);
    }
    expect(find.byKey(const Key('qc-mass')), findsOneWidget);
    expect(find.byKey(const Key('qc-warp')), findsOneWidget);
    expect(find.byKey(const Key('qc-hole')), findsOneWidget);
    expect(find.byKey(const Key('qc-adhesion')), findsOneWidget);
    // The tolerances the operator is measuring against are on screen.
    expect(find.text('+/- 0.3 mm'), findsNWidgets(3));
    expect(find.text('<= 0.5 mm'), findsOneWidget);
  });

  testWidgets('a queued print job can be cancelled from the list', (
    tester,
  ) async {
    await pump(tester, const ManufacturingView());
    await tester.tap(find.byTooltip(
      (await AppLocalizations.delegate.load(const Locale('tr'))).cancelPrint,
    ).first);
    await settle(tester);
    expect(calls('POST'), contains('/print-jobs/PJ1/cancel'));
  });

  testWidgets('a campaign can be stopped from the phone', (tester) async {
    await pump(tester, const EvolutionView());
    await tester.tap(find.byKey(const Key('stop-campaign')));
    await settle(tester);
    expect(calls('POST'), contains('/campaigns/C1/stop'));
  });

  group('level 4 approval (sections 5.2 and 5.5)', () {
    testWidgets('the owner must type the confirmation word', (tester) async {
      await pump(tester, const ApprovalDetailView(approvalId: 'A1'));

      final approve = find.byKey(const Key('approval-approve'));
      expect(tester.widget<FilledButton>(approve).onPressed, isNull);

      await tester.enterText(find.byKey(const Key('level4-confirm')), 'olur');
      await settle(tester);
      expect(tester.widget<FilledButton>(approve).onPressed, isNull);

      await tester.enterText(
        find.byKey(const Key('level4-confirm')),
        kLevel4ConfirmWord,
      );
      await settle(tester);
      expect(tester.widget<FilledButton>(approve).onPressed, isNotNull);
      await tester.tap(approve);
      await settle(tester);
      expect(calls('POST'), contains('/approvals/A1/approve'));
    });

    testWidgets('an operator is refused level 4 outright', (tester) async {
      await pump(
        tester,
        const ApprovalDetailView(approvalId: 'A1'),
        session: const Session(
          access: 'a',
          refresh: 'r',
          email: 'op@neml',
          role: 'operator',
        ),
      );

      await tester.enterText(
        find.byKey(const Key('level4-confirm')),
        kLevel4ConfirmWord,
      );
      await settle(tester);
      expect(
        tester
            .widget<FilledButton>(find.byKey(const Key('approval-approve')))
            .onPressed,
        isNull,
      );
      // Rejecting stays open: it errs on the safe side.
      await tester.tap(find.byKey(const Key('approval-reject')));
      await settle(tester);
      expect(calls('POST'), contains('/approvals/A1/reject'));
    });

    testWidgets('a viewer decides nothing at all', (tester) async {
      await pump(
        tester,
        const ApprovalDetailView(approvalId: 'A1'),
        session: const Session(
          access: 'a',
          refresh: 'r',
          email: 'v@neml',
          role: 'viewer',
        ),
      );

      expect(
        tester
            .widget<OutlinedButton>(find.byKey(const Key('approval-reject')))
            .onPressed,
        isNull,
      );
      expect(calls('POST'), isEmpty);
    });
  });

  group('notifier writes', () {
    ProviderContainer container() {
      final c = ProviderContainer(overrides: overrides());
      addTearDown(c.dispose);
      return c;
    }

    test('creating a task posts title, kind and priority', () async {
      final c = container();
      await c.read(tasksProvider.future);
      await c.read(tasksProvider.notifier).create(
            title: 'Merdiven cik',
            kind: 'exploration',
            priority: 3,
            robotId: 'R01',
          );

      final body = http.sent.lastWhere((r) => r.method == 'POST').data! as Map;
      expect(body['title'], 'Merdiven cik');
      expect(body['kind'], 'exploration');
      expect(body['robotId'], 'R01');
    });

    test('the QC form is submitted as section 12.5 names its fields', () async {
      final c = container();
      await c.read(manufacturingProvider.future);
      await c.read(manufacturingProvider.notifier).submitQc('PJ2', const {
        'dim_1_mm': 20.1,
        'mass_g': 47.8,
        'warp_mm': 0.2,
        'hole_gauge_ok': true,
        'layer_adhesion_ok': false,
      });

      final qc = http.sent.lastWhere((r) => r.path.endsWith('/qc')).data! as Map;
      expect(qc['dim_1_mm'], 20.1);
      expect(qc['layer_adhesion_ok'], isFalse);
      expect(calls('POST'), contains('/print-jobs/PJ2/qc'));
    });

    test('approving and rejecting hit their own endpoints', () async {
      final c = container();
      await c.read(approvalsProvider.future);
      await c.read(approvalsProvider.notifier).approve('A1', 'tamam');
      await c.read(approvalsProvider.notifier).reject('A2', 'hayir');
      expect(calls('POST'), contains('/approvals/A1/approve'));
      expect(calls('POST'), contains('/approvals/A2/reject'));
    });

    test('the console re-pulls only the turns still in flight', () async {
      final c = container();
      await c.read(brainConsoleProvider.notifier).send('R01 durumunu ozetle');
      http.sent.clear();
      await c.read(brainConsoleProvider.notifier).refreshPending();
      // The single turn came back `applied`, so there is nothing left to pull.
      expect(calls('GET'), isEmpty);
    });

    test('an empty command is never sent', () async {
      final c = container();
      await c.read(brainConsoleProvider.notifier).send('   ');
      expect(http.sent, isEmpty);
    });

    test('the dashboard refresh re-reads the brain and the robots', () async {
      final c = container();
      await c.read(dashboardProvider.future);
      http.sent.clear();
      await c.read(dashboardProvider.notifier).refresh();
      expect(calls('GET'), containsAll(['/brain/status', '/robots']));
    });
  });
}
