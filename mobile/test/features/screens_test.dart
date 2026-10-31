// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neml_mobile/core/config.dart';
import 'package:neml_mobile/core/router/router.dart';
import 'package:neml_mobile/l10n/app_localizations.dart';
import 'package:neml_mobile/features/approvals/approvals_view.dart';
import 'package:neml_mobile/features/brain_console/brain_console_view.dart';
import 'package:neml_mobile/features/dashboard/dashboard_view.dart';
import 'package:neml_mobile/features/evolution/evolution_view.dart';
import 'package:neml_mobile/features/genome_tree/genome_tree_view.dart';
import 'package:neml_mobile/features/login/login_view.dart';
import 'package:neml_mobile/features/logs/logs_view.dart';
import 'package:neml_mobile/features/manufacturing/manufacturing_view.dart';
import 'package:neml_mobile/features/robot_detail/robot_detail_view.dart';
import 'package:neml_mobile/features/settings/settings_view.dart';
import 'package:neml_mobile/features/skills/skills_view.dart';
import 'package:neml_mobile/features/task_detail/task_detail_view.dart';
import 'package:neml_mobile/features/tasks/tasks_view.dart';
import 'package:neml_mobile/main.dart';
import 'package:neml_mobile/shared/widgets.dart';

import '../helpers.dart';

/// The 13 screens of NEML_SPEC.md section 10.2, by the route that opens them.
const _screens = <String, Type>{
  '/': DashboardView,
  '/robots/R01': RobotDetailView,
  '/tasks': TasksView,
  '/tasks/T1': TaskDetailView,
  '/brain': BrainConsoleView,
  '/evolution': EvolutionView,
  '/genomes': GenomeTreeView,
  '/skills': SkillsView,
  '/approvals': ApprovalsView,
  '/approvals/A1': ApprovalDetailView,
  '/manufacturing': ManufacturingView,
  '/logs': LogsView,
  '/settings': SettingsView,
};

void main() {
  late FakeHttp http;

  setUp(() => http = FakeHttp());

  /// Boots the real app shell — router, theme and localisations included — in
  /// front of the fake API, and hands back its container.
  Future<ProviderContainer> boot(
    WidgetTester tester, {
    String locale = 'tr',
    bool signedIn = true,
    FakeHttp? server,
  }) async {
    final container = ProviderContainer(
      overrides: [
        ...apiOverrides(server ?? http, session: signedIn ? testSession : null),
        settingsProvider.overrideWith(
          () => SettingsNotifier(AppSettings(localeCode: locale)),
        ),
      ],
    );
    addTearDown(container.dispose);
    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const NemlApp()),
    );
    await settle(tester);
    return container;
  }

  for (final locale in const ['tr', 'en']) {
    testWidgets('every screen of section 10.2 renders in $locale', (
      tester,
    ) async {
      final container = await boot(tester, locale: locale);
      final router = container.read(routerProvider);

      for (final entry in _screens.entries) {
        router.go(entry.key);
        await settle(tester);
        expect(
          find.byType(entry.value),
          findsOneWidget,
          reason: '${entry.key} in $locale',
        );
        expect(find.byType(CircularProgressIndicator), findsNothing,
            reason: '${entry.key} in $locale still loading');
      }
    });
  }

  testWidgets('the dashboard shows the brain, the robots and the budgets', (
    tester,
  ) async {
    await boot(tester);

    expect(find.text('qwen2.5-coder-3b'), findsOneWidget);
    expect(find.text('R01'), findsWidgets);
    expect(find.text('R02'), findsWidgets);
    expect(find.text('llm_tokens'), findsOneWidget);
    expect(find.text('900 / 1000 ktok'), findsOneWidget);
    // Two pending approvals, so the badge is visible.
    expect(find.text('2'), findsWidgets);
  });

  testWidgets('a signed-out operator only ever sees the login screen', (
    tester,
  ) async {
    final container = await boot(tester, signedIn: false);
    expect(find.byType(LoginView), findsOneWidget);

    container.read(routerProvider).go('/approvals');
    await settle(tester);
    expect(find.byType(LoginView), findsOneWidget);
    expect(find.byType(ApprovalsView), findsNothing);
  });

  testWidgets('the drawer lists every section and navigates', (tester) async {
    // Tall enough for all ten destinations below the header.
    tester.view.physicalSize = const Size(800, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    final container = await boot(tester);
    final l10n = await AppLocalizations.delegate.load(const Locale('tr'));

    tester.firstState<ScaffoldState>(find.byType(Scaffold)).openDrawer();
    await settle(tester);

    for (final (path, icon) in kDestinations) {
      // The approvals icon also sits in the dashboard badge behind the drawer.
      expect(find.byIcon(icon), findsWidgets, reason: path);
      expect(
        find.text(destinationLabel(l10n, path)),
        findsWidgets,
        reason: path,
      );
    }

    await tester.tap(find.byIcon(Icons.settings_outlined));
    await settle(tester);
    expect(find.byType(SettingsView), findsOneWidget);
    expect(
      container.read(routerProvider).state.matchedLocation,
      '/settings',
    );
  });

  testWidgets('wide layout uses section navigation and preserves detail routes',
      (tester) async {
    tester.view.physicalSize = const Size(1400, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    final container = await boot(tester);
    expect(find.byKey(const Key('desktop-navigation')), findsOneWidget);
    expect(find.byType(Drawer), findsNothing);

    container.read(routerProvider).go('/robots/R01');
    await settle(tester);
    expect(find.byType(RobotDetailView), findsOneWidget);
    expect(find.byKey(const Key('desktop-navigation')), findsOneWidget);

    await tester.tap(find.byIcon(Icons.settings_outlined).last);
    await settle(tester);
    expect(find.byType(SettingsView), findsOneWidget);
  });
}
