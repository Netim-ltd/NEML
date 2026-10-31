// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neml_mobile/core/network/api.dart';
import 'package:neml_mobile/core/network/interceptors.dart';

import '../helpers.dart';

/// Every endpoint of NEML_SPEC.md section 9.3 as the app calls it: the path it
/// hits, the verb it uses and the model it hands back.
void main() {
  late FakeHttp http;
  late NemlApi api;

  setUp(() {
    http = FakeHttp();
    api = fakeApi(http);
  });

  RequestOptions lastCall() => http.sent.last;

  group('auth', () {
    test('login returns the session and its role', () async {
      final session = await api.login('mg@neml', 'sifre');
      expect(session.email, 'mg@neml');
      expect(session.role, 'owner');
      expect(session.canApprove, isTrue);
      expect(session.canApproveLevel4, isTrue);
      expect(lastCall().path, '/auth/login');
      expect((lastCall().data as Map)['password'], 'sifre');
    });

    test('logout and device registration post to section 9.3 paths', () async {
      await api.logout();
      expect(lastCall().path, '/auth/logout');

      await api.registerDevice('android', 'fcm-token');
      expect(lastCall().path, '/auth/devices');
      expect((lastCall().data as Map)['pushToken'], 'fcm-token');
    });

    test('devices lists the registered push targets', () async {
      final devices = await api.devices();
      expect(devices, hasLength(2));
      expect(devices.first.platform, 'android');
      expect(devices.first.current, isTrue);
      expect(devices.first.lastSeen, isNotNull);
      expect(devices.last.current, isFalse);
    });
  });

  group('robots', () {
    test('robots maps both wire spellings of battery_soc', () async {
      final robots = await api.robots();
      expect(robots.map((r) => r.id), ['R01', 'R02']);
      expect(robots.first.batterySoc, 0.82);
      expect(robots.first.currentTask, 'T1');
      expect(robots.first.genomeId, 'G1');
      expect(robots.first.realityGap, 0.041);
      expect(robots.last.batterySoc, 0.2);
    });

    test('a single robot carries its calibration', () async {
      final robot = await api.robot('R01');
      expect(robot.id, 'R01');
      expect(robot.state, 'running');
      expect(robot.calibratedAt, isNotNull);
    });

    test('telemetry sends the window and falls back to the asked metric',
        () async {
      final from = DateTime.utc(2026, 2, 1, 9, 59);
      final to = DateTime.utc(2026, 2, 1, 10, 1);
      final points = await api.telemetry(
        'R01',
        metric: 'battery_soc',
        from: from,
        to: to,
      );

      expect(points, hasLength(2));
      expect(points.first.value, 0.82);
      // The second sample has no `metric` key: the requested one is used.
      expect(points.last.metric, 'battery_soc');
      expect(lastCall().queryParameters['agg'], 'raw');
      expect(lastCall().queryParameters['from'], from.toIso8601String());
    });

    test('estop is a POST, never a GET', () async {
      await api.estop('R01');
      expect(lastCall().path, '/robots/R01/estop');
      expect(lastCall().method, 'POST');
    });
  });

  group('tasks', () {
    test('tasks drops null filters from the query string', () async {
      final tasks = await api.tasks(state: 'queued');
      expect(tasks, hasLength(3));
      expect(tasks.first.progress, 0.4);
      expect(tasks.first.spec['skill'], 'walk_flat');
      expect(tasks.first.deadline, isNotNull);
      expect(lastCall().queryParameters, {'state': 'queued'});
    });

    test('a single task exposes its result block', () async {
      final task = await api.task('T1');
      expect(task.id, 'T1');
      expect(task.state, 'failed');
      expect(task.result?['distance_m'], 1.2);
    });

    test('createTask posts the spec and omits a null robot', () async {
      final created = await api.createTask(
        title: 'Yeni',
        kind: 'human',
        priority: 2,
      );
      expect(created.id, 'T9');
      final body = lastCall().data as Map;
      expect(lastCall().path, '/tasks');
      expect(body['title'], 'Yeni');
      expect(body.containsKey('robotId'), isFalse);

      await api.createTask(
        title: 'Yeni',
        kind: 'human',
        priority: 2,
        robotId: 'R01',
        spec: const {'skill': 'walk_flat'},
      );
      expect((lastCall().data as Map)['robotId'], 'R01');
    });

    test('reprioritise patches and cancel posts', () async {
      await api.reprioritise('T1', 3.5);
      expect(lastCall().method, 'PATCH');
      expect((lastCall().data as Map)['priority'], 3.5);

      await api.cancelTask('T1');
      expect(lastCall().path, '/tasks/T1/cancel');
    });

    test('runs carry metrics and the rosbag path', () async {
      final runs = await api.runs('T1');
      expect(runs, hasLength(2));
      expect(runs.first.outcome, 'failure');
      expect(runs.first.metrics['distance_m'], 1.2);
      expect(runs.first.rosbagPath, '/data/rosbags/T1-1');
      expect(runs.last.outcome, isNull);
    });
  });

  group('brain', () {
    test('a command round-trips through send and fetch', () async {
      final sent = await api.sendCommand('  R01 durumunu ozetle  ');
      expect(sent.id, 'K1');
      expect(sent.state, 'delivered');

      final resolved = await api.command('K1');
      expect(resolved.intent, 'robot_status');
      expect(resolved.result?['summary'], 'idle');
    });

    test('brain status carries the budget rows of section 14.4', () async {
      final status = await api.brainStatus();
      expect(status.online, isTrue);
      expect(status.model, 'qwen2.5-coder-3b');
      expect(status.gpuOwner, 'brain');
      expect(status.budgets, hasLength(3));
      expect(status.budgets.first.ratio, 0.9);
      // A zero limit must not divide by zero.
      expect(status.budgets.last.ratio, 0);
    });
  });

  group('evolution', () {
    test('campaigns, generations and candidates', () async {
      final campaigns = await api.campaigns();
      expect(campaigns.single.id, 'C1');
      expect(campaigns.single.generation, 7);
      expect(campaigns.single.budgetRemaining, 120.5);

      final one = await api.campaign('C1');
      expect(one.name, 'Yuruyus optimizasyonu');

      final points = await api.generations('C1');
      expect(points.map((p) => p.generation), [6, 7]);
      expect(points.last.best, 0.8123);

      final candidates = await api.candidates('C1');
      expect(candidates.first.verdict, 'sim_pass');
      expect(candidates.last.operator, 'seed', reason: 'default of section 7');
    });

    test('stopCampaign posts to the stop path', () async {
      await api.stopCampaign('C1');
      expect(lastCall().path, '/campaigns/C1/stop');
      expect(lastCall().method, 'POST');
    });

    test('skills expose per-environment validations', () async {
      final skills = await api.skills();
      expect(skills, hasLength(2));
      final walk = skills.first;
      expect(walk.skillKey, 'walk_flat');
      expect(walk.forEnv('sim')!.rate, closeTo(0.91, 1e-9));
      expect(walk.forEnv('sim')!.failureModes, ['kayma']);
      expect(walk.forEnv('real')!.ci95High, 0.85);
      expect(walk.forEnv('bench'), isNull);
      expect(skills.last.validations, isEmpty);

      final versions = await api.skillVersions('walk_flat');
      expect(versions.map((s) => s.version), [3, 2]);
    });

    test('the genome tree keeps parent links', () async {
      final nodes = await api.genomeTree();
      expect(nodes, hasLength(3));
      expect(nodes[1].parentId, 'G1');
      expect(nodes[1].status, 'active');
      expect(nodes.first.hash, 'abc123');
    });
  });

  group('approvals', () {
    test('a pending list reads the payload block', () async {
      final approvals = await api.approvals();
      expect(approvals, hasLength(2));
      final first = approvals.first;
      expect(first.level, 4);
      expect(first.subjectKind, 'print_job');
      expect(first.summary, 'Bacak baglantisi v3 baski');
      expect(first.costTry, 42.5);
      expect(first.estTimeH, 3.25);
      expect(first.previewUrl, 'https://neml.test/preview.png');
      expect(first.remaining.isNegative, isFalse);
      expect(lastCall().queryParameters, {'pending': true});
    });

    test('a single approval reads the flat spelling', () async {
      final approval = await api.approval('A1');
      expect(approval.costTry, 42.5);
      expect(approval.decision, 'pending');
    });

    test('approve is a plain write', () async {
      await api.approve('A1', 'tamam');
      expect(lastCall().path, '/approvals/A1/approve');
      expect(lastCall().extra[kQueueWhenOffline], isNull);
    });

    test('reject is the one write flagged for the offline queue', () async {
      // Section 10.3: a rejection fails safe, so it may be parked in drift.
      await api.rejectApproval('A1', 'hayir');
      expect(lastCall().path, '/approvals/A1/reject');
      expect(lastCall().extra[kQueueWhenOffline], isTrue);
    });
  });

  group('manufacturing', () {
    test('print jobs map both wire spellings', () async {
      final jobs = await api.printJobs();
      expect(jobs, hasLength(3));
      expect(jobs.first.id, 'PJ1');
      expect(jobs.first.name, 'leg_link_v3');
      expect(jobs.first.printerId, 'P1');
      expect(jobs.first.estFilamentG, 48);
      expect(jobs[1].qc?['warp_mm'], 0.2);
      expect(jobs.last.estCostTry, isNull);
    });

    test('printer status carries temperatures and ETA', () async {
      final printer = await api.printerStatus('P1');
      expect(printer.id, 'P1');
      expect(printer.nozzleC, 214.5);
      expect(printer.targetBedC, 60);
      expect(printer.layer, 88);
      expect(printer.etaMin, 74);
      expect(printer.jobName, 'leg_link_v3');
    });

    test('cancel and QC submission post to section 12.5 paths', () async {
      await api.cancelPrint('PJ1');
      expect(lastCall().path, '/print-jobs/PJ1/cancel');

      await api.submitQc('PJ2', const {'warp_mm': 0.2, 'hole_gauge_ok': true});
      expect(lastCall().path, '/print-jobs/PJ2/qc');
      expect((lastCall().data as Map)['hole_gauge_ok'], isTrue);
    });
  });

  test('audit filters are optional', () async {
    final entries = await api.audit();
    expect(entries, hasLength(3));
    expect(entries.first.isToolCall, isTrue);
    expect(entries.first.durationMs, 1820);
    expect(entries[1].isToolCall, isFalse);
    expect(entries.last.isError, isTrue);
    expect(lastCall().queryParameters, isEmpty);

    await api.audit(actor: 'user:mg', outcome: 'ok');
    expect(lastCall().queryParameters, {'actor': 'user:mg', 'outcome': 'ok'});
  });

  test('an unknown endpoint degrades to the model defaults', () async {
    final robot = await api.robot('R99');
    expect(robot.id, '');
    expect(robot.state, 'offline');
    expect(await api.runs('T99'), isEmpty);
  });
}
