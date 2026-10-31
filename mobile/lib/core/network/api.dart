// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models.dart';
import 'dio_client.dart';
import 'interceptors.dart';

/// Thin typed wrapper over the endpoints of section 9.3. No caching or offline
/// logic lives here — that is the interceptors' job (section 10.3).
class NemlApi {
  NemlApi(this._dio);

  final Dio _dio;

  Future<Map<String, dynamic>> _get(
    String path, [
    Map<String, dynamic>? query,
  ]) async {
    final res = await _dio.get<dynamic>(path, queryParameters: query);
    final data = res.data;
    return data is Map
        ? data.map((k, v) => MapEntry('$k', v))
        : {'items': data};
  }

  Future<List<Map<String, dynamic>>> _list(
    String path, [
    Map<String, dynamic>? query,
  ]) async => mapList((await _get(path, query))['items'] ?? const []);

  // --- Auth (section 9.3) -------------------------------------------------
  Future<Session> login(String email, String password) async {
    final res = await _dio.post<Map<String, dynamic>>(
      '/auth/login',
      data: {'email': email, 'password': password},
    );
    return Session.fromJson(res.data ?? const {});
  }

  Future<void> logout() => _dio.post<void>('/auth/logout');

  Future<void> registerDevice(String platform, String pushToken) =>
      _dio.post<void>(
        '/auth/devices',
        data: {'platform': platform, 'pushToken': pushToken},
      );

  Future<List<DeviceSession>> devices() async =>
      (await _list('/auth/devices')).map(DeviceSession.fromJson).toList();

  // --- Robots -------------------------------------------------------------
  Future<List<Robot>> robots() async =>
      (await _list('/robots')).map(Robot.fromJson).toList();

  Future<Robot> robot(String id) async =>
      Robot.fromJson(await _get('/robots/$id'));

  Future<List<TelemetryPoint>> telemetry(
    String id, {
    required String metric,
    required DateTime from,
    required DateTime to,
    String agg = 'raw',
  }) async {
    final rows = await _list('/robots/$id/telemetry', {
      'metric': metric,
      'from': from.toUtc().toIso8601String(),
      'to': to.toUtc().toIso8601String(),
      'agg': agg,
    });
    return [
      for (final r in rows)
        TelemetryPoint(
          DateTime.tryParse('${r['ts']}')?.toLocal() ?? DateTime.now(),
          '${r['metric'] ?? metric}',
          double.tryParse('${r['value']}') ?? 0,
        ),
    ];
  }

  /// Queues an emergency stop. Guarded in the UI by a double-confirm slide
  /// (section 10.2 screen 3); the hard stop itself is L0 hardware (section 5.1).
  Future<void> estop(String id) => _dio.post<void>('/robots/$id/estop');

  // --- Tasks --------------------------------------------------------------
  Future<List<TaskItem>> tasks({String? state, String? kind, String? robot}) async {
    final rows = await _list('/tasks', {
      'state': ?state,
      'kind': ?kind,
      'robot': ?robot,
    });
    return rows.map(TaskItem.fromJson).toList();
  }

  Future<TaskItem> task(String id) async =>
      TaskItem.fromJson(await _get('/tasks/$id'));

  Future<TaskItem> createTask({
    required String title,
    required String kind,
    required double priority,
    String? robotId,
    Map<String, dynamic> spec = const {},
  }) async {
    final res = await _dio.post<Map<String, dynamic>>(
      '/tasks',
      data: {
        'title': title,
        'kind': kind,
        'priority': priority,
        'robotId': ?robotId,
        'spec': spec,
      },
    );
    return TaskItem.fromJson(res.data ?? const {});
  }

  Future<void> reprioritise(String id, double priority) =>
      _dio.patch<void>('/tasks/$id', data: {'priority': priority});

  Future<void> cancelTask(String id) => _dio.post<void>('/tasks/$id/cancel');

  Future<List<TaskRun>> runs(String id) async =>
      (await _list('/tasks/$id/runs')).map(TaskRun.fromJson).toList();

  // --- Brain --------------------------------------------------------------
  Future<BrainCommand> sendCommand(String text) async {
    final res = await _dio.post<Map<String, dynamic>>(
      '/brain/command',
      data: {'text': text},
    );
    return BrainCommand.fromJson(res.data ?? const {});
  }

  Future<BrainCommand> command(String id) async =>
      BrainCommand.fromJson(await _get('/brain/command/$id'));

  // --- Admin settings -----------------------------------------------------
  // The values live in the lab database, so a read or a write is a queued
  // command and the lab answers with a command_ack (section 3.1). These wait
  // for that ack and hand back its result.
  Future<Map<String, dynamic>> _labRoundTrip(
    Map<String, dynamic> accepted, {
    int attempts = 20,
  }) async {
    final id = '${accepted['commandId'] ?? accepted['id']}';
    for (var attempt = 0; attempt < attempts; attempt++) {
      await Future<void>.delayed(const Duration(milliseconds: 750));
      final c = await _get('/brain/command/$id');
      final state = '${c['state']}';
      final raw = c['result'];
      final result = raw is Map
          ? raw.map((k, v) => MapEntry('$k', v))
          : <String, dynamic>{};
      if (state == 'applied') return result;
      if (state == 'failed' || state == 'rejected') {
        throw Exception('${result['error'] ?? state}');
      }
    }
    throw Exception('lab did not answer (offline?)');
  }

  /// One operation of the learning lab (`{op: state}`, `{op: board, brief: ...}`);
  /// the lab answers through the command queue like the settings above.
  Future<Map<String, dynamic>> learningOp(Map<String, dynamic> body) async {
    final res = await _dio.post<Map<String, dynamic>>('/learning', data: body);
    return _labRoundTrip(res.data ?? const {}, attempts: 80);
  }

  Future<Map<String, dynamic>> modelSettingsList() async =>
      _labRoundTrip(await _get('/model-settings'));

  Future<Map<String, dynamic>> modelSettings(String modelId) async =>
      _labRoundTrip(await _get('/model-settings/$modelId'));

  Future<Map<String, dynamic>> saveModelSettings(
    String modelId,
    Map<String, double?> values,
  ) async {
    final res = await _dio.put<Map<String, dynamic>>(
      '/model-settings/$modelId',
      data: {'values': values},
    );
    return _labRoundTrip(res.data ?? const {});
  }

  Future<BrainStatus> brainStatus() async =>
      BrainStatus.fromJson(await _get('/brain/status'));

  // --- Evolution ----------------------------------------------------------
  Future<List<Campaign>> campaigns() async =>
      (await _list('/campaigns')).map(Campaign.fromJson).toList();

  Future<Campaign> campaign(String id) async =>
      Campaign.fromJson(await _get('/campaigns/$id'));

  Future<void> stopCampaign(String id) =>
      _dio.post<void>('/campaigns/$id/stop');

  Future<List<GenerationPoint>> generations(String id) async =>
      (await _list('/campaigns/$id/generations'))
          .map(GenerationPoint.fromJson)
          .toList();

  Future<List<Candidate>> candidates(String id) async =>
      (await _list('/campaigns/$id/candidates'))
          .map(Candidate.fromJson)
          .toList();

  Future<List<Skill>> skills() async =>
      (await _list('/skills')).map(Skill.fromJson).toList();

  Future<List<Skill>> skillVersions(String key) async =>
      (await _list('/skills/$key/versions')).map(Skill.fromJson).toList();

  Future<List<GenomeNode>> genomeTree() async =>
      (await _list('/genomes/tree')).map(GenomeNode.fromJson).toList();

  // --- Approvals ----------------------------------------------------------
  Future<List<Approval>> approvals({bool pending = true}) async =>
      (await _list('/approvals', {'pending': pending}))
          .map(Approval.fromJson)
          .toList();

  Future<Approval> approval(String id) async =>
      Approval.fromJson(await _get('/approvals/$id'));

  Future<void> approve(String id, String note) =>
      _dio.post<void>('/approvals/$id/approve', data: {'note': note});

  /// The single write allowed to survive being offline (section 10.3): a
  /// rejection fails safe, so it is queued in drift by [WriteGuardInterceptor].
  Future<void> rejectApproval(String id, String note) => _dio.post<void>(
    '/approvals/$id/reject',
    data: {'note': note},
    options: Options(extra: const {kQueueWhenOffline: true}),
  );

  // --- Manufacturing ------------------------------------------------------
  Future<List<PrintJob>> printJobs() async =>
      (await _list('/print-jobs')).map(PrintJob.fromJson).toList();

  Future<PrinterStatus> printerStatus(String id) async =>
      PrinterStatus.fromJson(await _get('/printers/$id/status'));

  Future<void> cancelPrint(String id) =>
      _dio.post<void>('/print-jobs/$id/cancel');

  /// Quality-control form of section 12.5 (caliper, pin gauge, scale).
  Future<void> submitQc(String jobId, Map<String, dynamic> qc) =>
      _dio.post<void>('/print-jobs/$jobId/qc', data: qc);

  // --- Audit --------------------------------------------------------------
  Future<List<AuditEntry>> audit({String? actor, String? outcome}) async =>
      (await _list('/audit', {
        'actor': ?actor,
        'outcome': ?outcome,
      })).map(AuditEntry.fromJson).toList();
}

final apiProvider = Provider<NemlApi>((ref) => NemlApi(ref.watch(dioProvider)));
