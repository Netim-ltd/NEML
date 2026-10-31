// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/approvals/approvals_view.dart';
import '../../features/boards/board_detail_view.dart';
import '../../features/boards/boards_view.dart';
import '../../features/brain_console/brain_console_view.dart';
import '../../features/dashboard/dashboard_view.dart';
import '../../features/evolution/evolution_view.dart';
import '../../features/genome_tree/genome_tree_view.dart';
import '../../features/login/login_view.dart';
import '../../features/logs/logs_view.dart';
import '../../features/manufacturing/manufacturing_view.dart';
import '../../features/robot_detail/robot_detail_view.dart';
import '../../features/settings/model_settings_view.dart';
import '../../features/settings/settings_view.dart';
import '../../features/skills/skills_view.dart';
import '../../features/task_detail/task_detail_view.dart';
import '../../features/tasks/tasks_view.dart';
import '../auth/auth.dart';
import '../models.dart';

const loginRoute = '/login';

/// Pure route guard: everything except the login screen needs a session, and a
/// signed-in operator never sits on the login screen.
///
/// Returns the path to redirect to, or `null` to stay put.
String? authRedirect({
  required AsyncValue<Session?> auth,
  required String location,
}) {
  // Still reading the keychain (possibly behind a biometric prompt): do not
  // bounce the operator around while that resolves.
  if (auth.isLoading) return null;
  final signedIn = auth.value != null;
  if (!signedIn) return location == loginRoute ? null : loginRoute;
  return location == loginRoute ? '/' : null;
}

final routerProvider = Provider<GoRouter>((ref) {
  final refresh = ValueNotifier<int>(0);
  ref.listen(authProvider, (_, _) => refresh.value++);
  ref.onDispose(refresh.dispose);

  return GoRouter(
    initialLocation: '/',
    refreshListenable: refresh,
    redirect: (context, state) =>
        authRedirect(auth: ref.read(authProvider), location: state.matchedLocation),
    routes: [
      GoRoute(path: loginRoute, builder: (_, _) => const LoginView()),
      GoRoute(path: '/', builder: (_, _) => const DashboardView()),
      GoRoute(
        path: '/robots/:id',
        builder: (_, s) => RobotDetailView(robotId: s.pathParameters['id']!),
      ),
      GoRoute(path: '/tasks', builder: (_, _) => const TasksView()),
      GoRoute(
        path: '/tasks/:id',
        builder: (_, s) => TaskDetailView(taskId: s.pathParameters['id']!),
      ),
      GoRoute(path: '/brain', builder: (_, _) => const BrainConsoleView()),
      GoRoute(path: '/evolution', builder: (_, _) => const EvolutionView()),
      GoRoute(path: '/genomes', builder: (_, _) => const GenomeTreeView()),
      GoRoute(path: '/skills', builder: (_, _) => const SkillsView()),
      GoRoute(path: '/approvals', builder: (_, _) => const ApprovalsView()),
      GoRoute(
        path: '/approvals/:id',
        builder: (_, s) => ApprovalDetailView(approvalId: s.pathParameters['id']!),
      ),
      GoRoute(
        path: '/manufacturing',
        builder: (_, _) => const ManufacturingView(),
      ),
      GoRoute(path: '/boards', builder: (_, _) => const BoardsView()),
      GoRoute(
        path: '/boards/:id',
        builder: (_, s) => BoardDetailView(boardId: s.pathParameters['id']!),
      ),
      GoRoute(path: '/logs', builder: (_, _) => const LogsView()),
      GoRoute(path: '/settings', builder: (_, _) => const SettingsView()),
      GoRoute(
        path: '/settings/models',
        builder: (_, _) => const ModelSettingsListView(),
      ),
      GoRoute(
        path: '/settings/models/:id',
        builder: (_, s) =>
            ModelSettingsDetailView(modelId: s.pathParameters['id']!),
      ),
    ],
  );
});
