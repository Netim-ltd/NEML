// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neml_mobile/core/models.dart';
import 'package:neml_mobile/core/push/push.dart';
import 'package:neml_mobile/features/genome_tree/genome_tree_provider.dart';
import 'package:neml_mobile/features/logs/logs_provider.dart';
import 'package:neml_mobile/features/robot_detail/robot_detail_provider.dart';
import 'package:neml_mobile/features/task_detail/task_detail_provider.dart';
import 'package:neml_mobile/features/tasks/tasks_provider.dart';

TaskItem _task(String id, String state, double priority) => TaskItem(
  id: id,
  title: id,
  kind: 'human',
  state: state,
  priority: priority,
);

GenomeNode _genome(String id, String? parent, int version, String status) =>
    GenomeNode(
      id: id,
      name: 'quadruped',
      version: version,
      status: status,
      parentId: parent,
    );

void main() {
  group('task tabs (section 10.2 screen 4)', () {
    final tasks = [
      _task('t1', 'queued', 1),
      _task('t2', 'awaiting_approval', 5),
      _task('t3', 'running', 2),
      _task('t4', 'paused', 3),
      _task('t5', 'succeeded', 9),
      _task('t6', 'cancelled', 8),
    ];

    test('queue holds queued, planning and awaiting_approval', () {
      expect(
        tasksForTab(tasks, TaskTab.queue).map((t) => t.id),
        ['t2', 't1'],
        reason: 'highest priority first',
      );
    });

    test('running holds running and paused', () {
      expect(tasksForTab(tasks, TaskTab.running).map((t) => t.id), ['t4', 't3']);
    });

    test('completed holds the terminal states', () {
      expect(
        tasksForTab(tasks, TaskTab.completed).map((t) => t.id),
        ['t5', 't6'],
      );
    });

    test('a live TaskUpdated only moves state and progress', () {
      final updated = _task(
        't1',
        'queued',
        1,
      ).mergeLive({'state': 'running', 'progress': 0.4});
      expect(updated.state, 'running');
      expect(updated.progress, 0.4);
      expect(updated.priority, 1);
      expect(updated.title, 't1');
    });
  });

  group('genome lineage (section 10.2 screen 8)', () {
    test('children are indented under their parent', () {
      final rows = lineageRows([
        _genome('g2', 'g1', 2, 'active'),
        _genome('g1', null, 1, 'deprecated'),
        _genome('g3', 'g2', 3, 'testing'),
      ]);
      expect(rows.map((r) => r.node.id), ['g1', 'g2', 'g3']);
      expect(rows.map((r) => r.depth), [0, 1, 2]);
    });

    test('a parent outside the returned set becomes a root', () {
      final rows = lineageRows([_genome('g9', 'missing', 9, 'draft')]);
      expect(rows.single.depth, 0);
    });
  });

  group('log tabs (section 10.2 screen 12)', () {
    final entries = [
      AuditEntry(ts: DateTime(2026), actor: 'user:mg', action: 'approve'),
      AuditEntry(
        ts: DateTime(2026),
        actor: 'agent:mechanical',
        action: 'cad.export',
        outcome: 'ok',
      ),
      AuditEntry(
        ts: DateTime(2026),
        actor: 'agent:fab',
        action: 'slice',
        outcome: 'failure',
      ),
    ];

    test('tool calls are the agent actors', () {
      expect(logsForTab(entries, LogTab.toolCalls, '').length, 2);
    });

    test('errors are the failed outcomes', () {
      expect(logsForTab(entries, LogTab.errors, '').single.action, 'slice');
    });

    test('the filter matches actor, action or target', () {
      expect(logsForTab(entries, LogTab.audit, 'cad').single.action, 'cad.export');
      expect(logsForTab(entries, LogTab.audit, 'user').single.action, 'approve');
      expect(logsForTab(entries, LogTab.audit, 'zzz'), isEmpty);
    });
  });

  group('telemetry window (section 10.2 screen 3)', () {
    test('keeps only the last 60 seconds', () {
      final now = DateTime(2026, 9, 15, 12, 0, 0);
      final points = [
        TelemetryPoint(now.subtract(const Duration(seconds: 90)), 'x', 1),
        TelemetryPoint(now.subtract(const Duration(seconds: 61)), 'x', 2),
        TelemetryPoint(now.subtract(const Duration(seconds: 59)), 'x', 3),
        TelemetryPoint(now, 'x', 4),
      ];
      expect(trimWindow(points, now).map((p) => p.value), [3, 4]);
    });
  });

  group('push rules (section 10.4)', () {
    test('approval and robot faults are high priority with sound', () {
      expect(ruleFor('approval_requested').importance, Importance.high);
      expect(ruleFor('approval_requested').sound, isTrue);
      expect(ruleFor('robot_fault').importance, Importance.high);
      expect(ruleFor('robot_fault').sound, isTrue);
    });

    test('normal priority triggers are silent', () {
      for (final trigger in ['task_failed', 'campaign_completed', 'budget_90']) {
        expect(ruleFor(trigger).importance, Importance.defaultImportance);
        expect(ruleFor(trigger).sound, isFalse);
      }
    });

    test('a finished print is low priority and silent', () {
      expect(ruleFor('print_finished').importance, Importance.low);
      expect(ruleFor('print_finished').sound, isFalse);
    });

    test('an unknown trigger never escalates to high with sound', () {
      expect(ruleFor('whatever').importance, Importance.defaultImportance);
      expect(ruleFor(null).sound, isFalse);
    });
  });

  group('task detail helpers (section 10.2 screen 5)', () {
    test('spec JSON is indented for reading', () {
      expect(prettyJson({'a': 1}), '{\n  "a": 1\n}');
    });

    test('failure modes are read from either spelling', () {
      final task = TaskItem(
        id: 't',
        title: 't',
        kind: 'human',
        state: 'failed',
        priority: 1,
        result: const {
          'failure_modes': ['slip', 'timeout'],
        },
      );
      expect(failureModesOf(task), ['slip', 'timeout']);
    });

    test('no result means no failure modes', () {
      expect(failureModesOf(_task('t', 'queued', 1)), isEmpty);
    });
  });

  group('wire parsing', () {
    test('budget ratio is clamped and safe against a zero limit', () {
      expect(const Budget(key: 'gpu', used: 3, limit: 6, unit: 'h').ratio, 0.5);
      expect(const Budget(key: 'x', used: 9, limit: 6, unit: 'h').ratio, 1.0);
      expect(const Budget(key: 'x', used: 1, limit: 0, unit: 'h').ratio, 0);
    });

    test('a page envelope and a bare array both parse', () {
      expect(mapList([{'id': 'a'}]).single['id'], 'a');
      expect(
        mapList({
          'items': [
            {'id': 'b'},
          ],
        }).single['id'],
        'b',
      );
      expect(mapList(null), isEmpty);
    });

    test('a skill validation exposes the observed rate', () {
      final v = SkillValidation.fromJson(const {
        'env': 'real',
        'trials': 20,
        'successes': 17,
        'ci95_low': 0.62,
        'ci95_high': 0.94,
      });
      expect(v.rate, closeTo(0.85, 1e-9));
      expect(v.env, 'real');
    });
  });
}
