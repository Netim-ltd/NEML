// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:neml_mobile/core/auth/auth.dart';
import 'package:neml_mobile/core/models.dart';
import 'package:neml_mobile/core/network/api.dart';
import 'package:neml_mobile/core/network/dio_client.dart';
import 'package:neml_mobile/core/network/online.dart';
import 'package:neml_mobile/core/realtime/live_client.dart';
import 'package:neml_mobile/l10n/app_localizations.dart';

/// Wraps a widget in the localisation + Riverpod scaffolding the app provides,
/// in Turkish (the primary locale of section 10.1).
Widget wrap(Widget child, {List<Override> overrides = const []}) =>
    ProviderScope(
      overrides: overrides,
      child: MaterialApp(
        locale: const Locale('tr'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(body: child),
      ),
    );

class FakeOnline extends OnlineNotifier {
  FakeOnline(this.initial);

  final ConnStatus initial;

  @override
  ConnStatus build() => initial;
}

Override offlineSince(DateTime lastSync) => onlineProvider.overrideWith(
  () => FakeOnline(ConnStatus(online: false, lastSync: lastSync)),
);

// --- Fake API ---------------------------------------------------------------

const testSession = Session(
  access: 'access-token',
  refresh: 'refresh-token',
  email: 'mg@neml',
  role: 'owner',
);

class FakeAuth extends AuthNotifier {
  FakeAuth(this.session);

  final Session? session;

  @override
  Future<Session?> build() async => session;
}

/// Serves canned JSON for the endpoints of section 9.3, keyed by request path,
/// or by `'<VERB> <path>'` where the verb changes the shape (`GET /tasks` is a
/// list, `POST /tasks` is the created row). An unknown path answers `{}`,
/// which every model maps to its defaults.
class FakeHttp implements HttpClientAdapter {
  FakeHttp({Map<String, Object?>? routes, this.status = 200})
    : routes = routes ?? fakeRoutes();

  final Map<String, Object?> routes;
  final int status;

  /// Every request that reached the adapter, in order.
  final sent = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    sent.add(options);
    return ResponseBody.fromString(
      jsonEncode(
        routes['${options.method} ${options.path}'] ??
            routes[options.path] ??
            const <String, dynamic>{},
      ),
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

/// A [NemlApi] with no server in the loop.
NemlApi fakeApi(FakeHttp http) => NemlApi(
  Dio(BaseOptions(baseUrl: 'https://neml.test$kApiPrefix'))
    ..httpClientAdapter = http,
);

/// One populated row per screen of section 10.2. Both wire spellings appear on
/// purpose (`batterySoc` and `battery_soc`), because the models accept both.
Map<String, Object?> fakeRoutes() => {
  '/auth/login': testSession.toJson(),
  '/auth/devices': [
    {'id': 'd1', 'platform': 'android', 'last_seen': '2026-02-01T09:00:00Z',
      'current': true},
    {'id': 'd2', 'platform': 'ios'},
  ],
  '/brain/status': {
    'online': true,
    'model': 'qwen2.5-coder-3b',
    'gpu_owner': 'brain',
    'budgetUsed': [
      {'key': 'llm_tokens', 'used': 900, 'limit': 1000, 'unit': 'ktok'},
      {'key': 'sim_minutes', 'used': 10, 'limit': 240, 'unit': 'min'},
      {'key': 'filament_g', 'used': 0, 'limit': 0, 'unit': 'g'},
    ],
  },
  '/brain/command': {
    'id': 'K1',
    'text': 'R01 durumunu ozetle',
    'state': 'delivered',
  },
  '/brain/command/K1': {
    'id': 'K1',
    'text': 'R01 durumunu ozetle',
    'state': 'applied',
    'intent': 'robot_status',
    'change': 'yok',
    'result': {'summary': 'idle'},
  },
  '/robots': [
    {
      'id': 'R01',
      'state': 'running',
      'battery_soc': 0.82,
      'last_seen': '2026-02-01T10:00:00Z',
      'currentTask': 'T1',
      'genome_id': 'G1',
      'calibrated_at': '2026-01-30T10:00:00Z',
      'reality_gap': 0.041,
    },
    {'id': 'R02', 'state': 'charging', 'batterySoc': 0.2},
  ],
  '/robots/R01': {
    'robotId': 'R01',
    'state': 'running',
    'batterySoc': 0.82,
    'calibratedAt': '2026-01-30T10:00:00Z',
    'realityGap': 0.041,
  },
  '/robots/R01/telemetry': {
    'items': [
      {'ts': '2026-02-01T10:00:00Z', 'metric': 'battery_soc', 'value': 0.82},
      {'ts': '2026-02-01T10:00:30Z', 'value': 0.81},
    ],
  },
  '/tasks': [
    {
      'id': 'T1',
      'title': 'Duz zeminde yuru',
      'kind': 'exploration',
      'state': 'running',
      'priority': 2.5,
      'robotId': 'R01',
      'progress': 0.4,
      'spec': {'skill': 'walk_flat'},
      'createdAt': '2026-02-01T08:00:00Z',
      'deadline': '2026-02-02T08:00:00Z',
    },
    {'id': 'T2', 'title': 'Kalibrasyon', 'kind': 'calibration',
      'state': 'queued', 'priority': 1},
    {'id': 'T3', 'title': 'Onarim', 'kind': 'repair', 'state': 'succeeded',
      'priority': 0.5},
  ],
  'POST /tasks': {'id': 'T9', 'title': 'Yeni', 'kind': 'human',
    'state': 'queued', 'priority': 2},
  '/tasks/T1': {
    'taskId': 'T1',
    'title': 'Duz zeminde yuru',
    'kind': 'exploration',
    'state': 'failed',
    'priority': 2.5,
    'spec': {'skill': 'walk_flat', 'distance_m': 3},
    'result': {'failure_modes': ['dizde kayma'], 'distance_m': 1.2},
  },
  '/tasks/T1/runs': [
    {
      'attempt': 1,
      'env': 'sim',
      'outcome': 'failure',
      'startedAt': '2026-02-01T09:00:00Z',
      'endedAt': '2026-02-01T09:02:00Z',
      'metrics': {'distance_m': 1.2},
      'rosbagPath': '/data/rosbags/T1-1',
    },
    {'attempt': 2, 'env': 'bench'},
  ],
  '/approvals': [
    {
      'id': 'A1',
      'level': 4,
      'subject_kind': 'print_job',
      'subject_id': 'PJ1',
      'subject': 'Bacak baglantisi v3 baski',
      'expires_at': '2099-01-01T00:00:00Z',
      'requested_at': '2026-02-01T09:00:00Z',
      'payload': {'costTry': 42.5, 'estTimeH': 3.25,
        'previewUrl': 'https://neml.test/preview.png'},
    },
    {'id': 'A2', 'level': 2, 'subjectKind': 'deployment',
      'subjectId': 'G2', 'expiresAt': '2099-01-01T00:00:00Z'},
  ],
  '/approvals/A1': {
    'id': 'A1',
    'level': 4,
    'subjectKind': 'print_job',
    'subjectId': 'PJ1',
    'subject': 'Bacak baglantisi v3 baski',
    'expiresAt': '2099-01-01T00:00:00Z',
    'previewUrl': 'https://neml.test/preview.png',
    'costTry': 42.5,
    'estTimeH': 3.25,
    'decision': 'pending',
    'note': '',
  },
  '/campaigns': [
    {
      'campaignId': 'C1',
      'name': 'Yuruyus optimizasyonu',
      'objective': 'max mesafe / min enerji',
      'state': 'active',
      'generation': 7,
      'best': 0.8123,
      'mean': 0.6421,
      'budgetRemaining': 120.5,
    },
  ],
  '/campaigns/C1': {'id': 'C1', 'name': 'Yuruyus optimizasyonu',
    'objective': 'max mesafe', 'state': 'active'},
  '/campaigns/C1/generations': [
    {'generation': 6, 'best': 0.71, 'mean': 0.6},
    {'generation': 7, 'best': 0.8123, 'mean': 0.6421},
  ],
  '/campaigns/C1/candidates': [
    {'id': 'CA1', 'generation': 7, 'operator': 'mutation', 'fitness': 0.8123,
      'verdict': 'sim_pass', 'rationale': 'diz acisi artirildi'},
    {'id': 'CA2', 'generation': 7},
  ],
  '/skills': [
    {
      'id': 'S1',
      'skill_key': 'walk_flat',
      'version': 3,
      'status': 'validated',
      'preconditions': {'battery_soc': 0.3},
      'validations': [
        {'env': 'sim', 'trials': 100, 'successes': 91, 'ci95_low': 0.84,
          'ci95_high': 0.95, 'failure_modes': ['kayma']},
        {'env': 'real', 'trials': 20, 'successes': 14, 'ci95Low': 0.48,
          'ci95High': 0.85},
      ],
    },
    {'id': 'S2', 'skillKey': 'stand_up', 'version': 1},
  ],
  '/skills/walk_flat/versions': [
    {'id': 'S1', 'skillKey': 'walk_flat', 'version': 3, 'status': 'validated'},
    {'id': 'S0', 'skillKey': 'walk_flat', 'version': 2, 'status': 'retired'},
  ],
  '/skills/stand_up/versions': <Object?>[],
  '/genomes/tree': [
    {'id': 'G1', 'name': 'quadruped', 'version': 1, 'status': 'deprecated',
      'hash': 'abc123', 'fitnessScore': 0.5},
    {'id': 'G2', 'name': 'quadruped', 'version': 2, 'status': 'active',
      'parentId': 'G1', 'fitnessScore': 0.81},
    {'id': 'G3', 'name': 'quadruped', 'version': 3, 'status': 'draft',
      'parentId': 'G9'},
  ],
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
    {'id': 'PJ2', 'state': 'done', 'printerId': 'P1',
      'qc': {'warp_mm': 0.2}},
    {'id': 'PJ3', 'state': 'queued', 'printerId': 'P1'},
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
  '/audit': [
    {'ts': '2026-02-01T09:00:00Z', 'actor': 'agent:mechanical',
      'action': 'cad.generate', 'target': 'leg_link_v3', 'outcome': 'ok',
      'duration_ms': 1820},
    {'ts': '2026-02-01T09:05:00Z', 'actor': 'user:mg', 'action': 'approve',
      'target': 'A1', 'outcome': 'ok', 'approvalId': 'A1'},
    {'ts': '2026-02-01T09:10:00Z', 'actor': 'agent:fab', 'action': 'slice',
      'outcome': 'error'},
  ],
};

/// Overrides that put a whole screen in front of the fake API, signed in as
/// [session] and with the SignalR hub out of the picture.
List<Override> apiOverrides(FakeHttp http, {Session? session = testSession}) => [
  apiProvider.overrideWithValue(fakeApi(http)),
  authProvider.overrideWith(() => FakeAuth(session)),
  liveClientProvider.overrideWithValue(null),
];

/// Advances enough frames for the async providers to resolve without waiting
/// for the approval countdown's 1 Hz timer, which never settles.
Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 8; i++) {
    await tester.pump(const Duration(milliseconds: 40));
  }
}
