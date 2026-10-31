// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

/// Wire models for the .NET API (NEML_SPEC.md section 9.3) and the SignalR
/// payloads (section 9.4). Only the fields the screens render are mapped.
///
/// ponytail: hand-written `fromJson`, no code generation. Swap to
/// json_serializable if the payload set triples.
library;

String _s(Object? v, [String fallback = '']) => v?.toString() ?? fallback;
double? _d(Object? v) => v == null ? null : double.tryParse(v.toString());
int? _i(Object? v) =>
    v == null ? null : int.tryParse(v.toString().split('.').first);
DateTime? _dt(Object? v) =>
    v == null ? null : DateTime.tryParse(v.toString())?.toLocal();

Map<String, dynamic> _map(Object? v) => v is Map
    ? v.map((k, val) => MapEntry(k.toString(), val))
    : <String, dynamic>{};

/// Accepts both a bare JSON array and a `{items: [...]}` page envelope.
List<Map<String, dynamic>> mapList(Object? v) {
  final items = v is List
      ? v
      : (v is Map && v['items'] is List ? v['items'] as List : const []);
  return items.map(_map).toList(growable: false);
}

/// Signed-in user plus the JWT pair from `POST /auth/login` (section 5.5).
class Session {
  const Session({
    required this.access,
    required this.refresh,
    required this.email,
    required this.role,
  });

  factory Session.fromJson(Map<String, dynamic> j) => Session(
    access: _s(j['access']),
    refresh: _s(j['refresh']),
    email: _s(j['email']),
    role: _s(j['role'], 'viewer'),
  );

  final String access;
  final String refresh;
  final String email;

  /// `owner` | `operator` | `viewer` (section 5.5).
  final String role;

  /// Approval authority is limited to owner and operator (section 5.5).
  bool get canApprove => role == 'owner' || role == 'operator';

  /// Level 4 (MANUFACTURE) may only be approved by the owner (section 5.5).
  bool get canApproveLevel4 => role == 'owner';

  Session copyWith({String? access, String? refresh}) => Session(
    access: access ?? this.access,
    refresh: refresh ?? this.refresh,
    email: email,
    role: role,
  );

  Map<String, dynamic> toJson() => {
    'access': access,
    'refresh': refresh,
    'email': email,
    'role': role,
  };
}

/// One row of the daily budget table (section 14.4).
class Budget {
  const Budget({
    required this.key,
    required this.used,
    required this.limit,
    required this.unit,
  });

  factory Budget.fromJson(Map<String, dynamic> j) => Budget(
    key: _s(j['key']),
    used: _d(j['used']) ?? 0,
    limit: _d(j['limit']) ?? 0,
    unit: _s(j['unit']),
  );

  final String key;
  final double used;
  final double limit;
  final String unit;

  double get ratio => limit <= 0 ? 0 : (used / limit).clamp(0.0, 1.0);
}

/// `GET /brain/status` and the SignalR `BrainStatus` event.
class BrainStatus {
  const BrainStatus({
    required this.online,
    required this.model,
    required this.gpuOwner,
    this.budgets = const [],
  });

  factory BrainStatus.fromJson(Map<String, dynamic> j) => BrainStatus(
    online: j['online'] == true,
    model: _s(j['model'], '-'),
    gpuOwner: _s(j['gpuOwner'] ?? j['gpu_owner'], '-'),
    budgets: mapList(
      j['budgetUsed'] ?? j['budgets'],
    ).map(Budget.fromJson).toList(),
  );

  final bool online;
  final String model;
  final String gpuOwner;
  final List<Budget> budgets;
}

class Robot {
  const Robot({
    required this.id,
    required this.state,
    this.batterySoc,
    this.lastSeen,
    this.currentTask,
    this.genomeId = '',
    this.calibratedAt,
    this.realityGap,
  });

  factory Robot.fromJson(Map<String, dynamic> j) => Robot(
    id: _s(j['id'] ?? j['robotId']),
    state: _s(j['state'], 'offline'),
    batterySoc: _d(j['batterySoc'] ?? j['battery_soc']),
    lastSeen: _dt(j['lastSeen'] ?? j['last_seen']),
    currentTask: j['currentTask'] == null ? null : _s(j['currentTask']),
    genomeId: _s(j['genomeId'] ?? j['genome_id']),
    calibratedAt: _dt(j['calibratedAt'] ?? j['calibrated_at']),
    realityGap: _d(j['realityGap'] ?? j['reality_gap']),
  );

  final String id;

  /// `offline|idle|charging|running|fault|estop|maintenance` (section 7).
  final String state;
  final double? batterySoc;
  final DateTime? lastSeen;
  final String? currentTask;
  final String genomeId;
  final DateTime? calibratedAt;
  final double? realityGap;

  /// Applies a SignalR `RobotState` payload on top of the cached row.
  Robot mergeLive(Map<String, dynamic> j) => Robot(
    id: id,
    state: _s(j['state'], state),
    batterySoc: _d(j['batterySoc']) ?? batterySoc,
    lastSeen: _dt(j['lastSeen']) ?? lastSeen,
    currentTask: currentTask,
    genomeId: genomeId,
    calibratedAt: calibratedAt,
    realityGap: realityGap,
  );
}

/// One sample of one metric; the robot chart keeps a 60 s window of these
/// (section 10.2 screen 3).
class TelemetryPoint {
  const TelemetryPoint(this.ts, this.metric, this.value);

  final DateTime ts;
  final String metric;
  final double value;
}

class TaskItem {
  const TaskItem({
    required this.id,
    required this.title,
    required this.kind,
    required this.state,
    required this.priority,
    this.robotId,
    this.progress,
    this.spec = const {},
    this.result,
    this.deadline,
    this.createdAt,
  });

  factory TaskItem.fromJson(Map<String, dynamic> j) => TaskItem(
    id: _s(j['id'] ?? j['taskId']),
    title: _s(j['title']),
    kind: _s(j['kind'], 'human'),
    state: _s(j['state'], 'queued'),
    priority: _d(j['priority']) ?? 0,
    robotId: j['robotId'] == null ? null : _s(j['robotId']),
    progress: _d(j['progress']),
    spec: _map(j['spec']),
    result: j['result'] == null ? null : _map(j['result']),
    deadline: _dt(j['deadline']),
    createdAt: _dt(j['createdAt']),
  );

  final String id;
  final String title;

  /// `human|repair|exploration|evolution|maintenance|calibration` (section 7).
  final String kind;

  /// `queued|planning|awaiting_approval|running|paused|succeeded|failed|cancelled`.
  final String state;
  final double priority;
  final String? robotId;
  final double? progress;
  final Map<String, dynamic> spec;
  final Map<String, dynamic>? result;
  final DateTime? deadline;
  final DateTime? createdAt;

  /// Applies a SignalR `TaskUpdated` payload on top of the cached row.
  TaskItem mergeLive(Map<String, dynamic> j) => TaskItem(
    id: id,
    title: title,
    kind: kind,
    state: _s(j['state'], state),
    priority: priority,
    robotId: robotId,
    progress: _d(j['progress']) ?? progress,
    spec: spec,
    result: result,
    deadline: deadline,
    createdAt: createdAt,
  );

  static const queuedStates = {'queued', 'planning', 'awaiting_approval'};
  static const runningStates = {'running', 'paused'};
  static const doneStates = {'succeeded', 'failed', 'cancelled'};
}

class TaskRun {
  const TaskRun({
    required this.attempt,
    required this.env,
    this.outcome,
    this.startedAt,
    this.endedAt,
    this.metrics = const {},
    this.rosbagPath,
  });

  factory TaskRun.fromJson(Map<String, dynamic> j) => TaskRun(
    attempt: _i(j['attempt']) ?? 0,
    env: _s(j['env'], 'sim'),
    outcome: j['outcome'] == null ? null : _s(j['outcome']),
    startedAt: _dt(j['startedAt']),
    endedAt: _dt(j['endedAt']),
    metrics: _map(j['metrics']),
    rosbagPath: j['rosbagPath'] == null ? null : _s(j['rosbagPath']),
  );

  final int attempt;

  /// `sim|bench|tethered|free` (section 7).
  final String env;

  /// `success|failure|aborted|timeout`.
  final String? outcome;
  final DateTime? startedAt;
  final DateTime? endedAt;
  final Map<String, dynamic> metrics;
  final String? rosbagPath;
}

/// A deployment gate waiting on a human (sections 5.2, 10.2 screen 10).
class Approval {
  const Approval({
    required this.id,
    required this.level,
    required this.subjectKind,
    required this.subjectId,
    required this.summary,
    required this.expiresAt,
    this.previewUrl,
    this.costTry,
    this.estTimeH,
    this.requestedAt,
    this.decision,
    this.note,
  });

  factory Approval.fromJson(Map<String, dynamic> j) {
    final payload = _map(j['payload']);
    return Approval(
      id: _s(j['id'] ?? j['approvalId']),
      level: _i(j['level']) ?? 1,
      subjectKind: _s(j['subjectKind'] ?? j['subject_kind']),
      subjectId: _s(j['subjectId'] ?? j['subject_id']),
      summary: _s(j['subject'] ?? payload['summary']),
      expiresAt: _dt(j['expiresAt'] ?? j['expires_at']) ?? DateTime.now(),
      previewUrl: (j['previewUrl'] ?? payload['previewUrl']) == null
          ? null
          : _s(j['previewUrl'] ?? payload['previewUrl']),
      costTry: _d(payload['costTry'] ?? j['costTry']),
      estTimeH: _d(payload['estTimeH'] ?? j['estTimeH']),
      requestedAt: _dt(j['requestedAt'] ?? j['requested_at']),
      decision: j['decision'] == null ? null : _s(j['decision']),
      note: j['note'] == null ? null : _s(j['note']),
    );
  }

  final String id;

  /// 1 BENCH, 2 TETHERED, 3 FREE, 4 MANUFACTURE (section 5.2).
  final int level;
  final String subjectKind;
  final String subjectId;
  final String summary;
  final DateTime expiresAt;
  final String? previewUrl;
  final double? costTry;
  final double? estTimeH;
  final DateTime? requestedAt;
  final String? decision;
  final String? note;

  Duration get remaining => expiresAt.difference(DateTime.now());
}

class Campaign {
  const Campaign({
    required this.id,
    required this.name,
    required this.objective,
    required this.state,
    this.generation = 0,
    this.best,
    this.mean,
    this.budgetRemaining,
  });

  factory Campaign.fromJson(Map<String, dynamic> j) => Campaign(
    id: _s(j['id'] ?? j['campaignId']),
    name: _s(j['name']),
    objective: _s(j['objective']),
    state: _s(j['state'], 'active'),
    generation: _i(j['generation']) ?? 0,
    best: _d(j['best']),
    mean: _d(j['mean']),
    budgetRemaining: _d(j['budgetRemaining']),
  );

  final String id;
  final String name;
  final String objective;

  /// `active|stopped|completed` (section 7).
  final String state;
  final int generation;
  final double? best;
  final double? mean;
  final double? budgetRemaining;

  /// Applies a SignalR `CampaignProgress` payload.
  Campaign mergeProgress(Map<String, dynamic> j) => Campaign(
    id: id,
    name: name,
    objective: objective,
    state: state,
    generation: _i(j['generation']) ?? generation,
    best: _d(j['best']) ?? best,
    mean: _d(j['mean']) ?? mean,
    budgetRemaining: budgetRemaining,
  );
}

/// One point of the fitness curve (`GET /campaigns/{id}/generations`).
class GenerationPoint {
  const GenerationPoint(this.generation, this.best, this.mean);

  factory GenerationPoint.fromJson(Map<String, dynamic> j) => GenerationPoint(
    _i(j['generation']) ?? 0,
    _d(j['best']) ?? 0,
    _d(j['mean']) ?? 0,
  );

  final int generation;
  final double best;
  final double mean;
}

class Candidate {
  const Candidate({
    required this.id,
    required this.generation,
    required this.operator,
    this.fitness,
    this.verdict,
    this.rationale,
  });

  factory Candidate.fromJson(Map<String, dynamic> j) => Candidate(
    id: _s(j['id']),
    generation: _i(j['generation']) ?? 0,
    operator: _s(j['operator'], 'seed'),
    fitness: _d(j['fitness']),
    verdict: j['verdict'] == null ? null : _s(j['verdict']),
    rationale: j['rationale'] == null ? null : _s(j['rationale']),
  );

  final String id;
  final int generation;

  /// `mutation|crossover|llm_guided|seed` (section 7).
  final String operator;
  final double? fitness;

  /// `pending|sim_pass|sim_fail|real_pass|real_fail|accepted|rejected`.
  final String? verdict;
  final String? rationale;
}

/// A node of `GET /genomes/tree`.
class GenomeNode {
  const GenomeNode({
    required this.id,
    required this.name,
    required this.version,
    required this.status,
    this.parentId,
    this.fitnessScore,
    this.hash = '',
  });

  factory GenomeNode.fromJson(Map<String, dynamic> j) => GenomeNode(
    id: _s(j['id']),
    name: _s(j['name']),
    version: _i(j['version']) ?? 0,
    status: _s(j['status'], 'draft'),
    parentId: j['parentId'] == null ? null : _s(j['parentId']),
    fitnessScore: _d(j['fitnessScore']),
    hash: _s(j['hash']),
  );

  final String id;
  final String name;
  final int version;

  /// `draft|testing|active|deprecated` (section 7).
  final String status;
  final String? parentId;
  final double? fitnessScore;
  final String hash;
}

/// Sim or real validation of a skill with its Wilson interval
/// (section 7 `skill_validations`).
class SkillValidation {
  const SkillValidation({
    required this.env,
    required this.trials,
    required this.successes,
    required this.ci95Low,
    required this.ci95High,
    this.failureModes = const [],
  });

  factory SkillValidation.fromJson(Map<String, dynamic> j) {
    final modes = j['failureModes'] ?? j['failure_modes'];
    return SkillValidation(
      env: _s(j['env'], 'sim'),
      trials: _i(j['trials']) ?? 0,
      successes: _i(j['successes']) ?? 0,
      ci95Low: _d(j['ci95Low'] ?? j['ci95_low']) ?? 0,
      ci95High: _d(j['ci95High'] ?? j['ci95_high']) ?? 0,
      failureModes: modes is List
          ? modes.map((m) => _s(m)).toList()
          : const <String>[],
    );
  }

  final String env;
  final int trials;
  final int successes;
  final double ci95Low;
  final double ci95High;
  final List<String> failureModes;

  double get rate => trials == 0 ? 0 : successes / trials;
}

class Skill {
  const Skill({
    required this.id,
    required this.skillKey,
    required this.version,
    required this.status,
    this.preconditions = const {},
    this.validations = const [],
  });

  factory Skill.fromJson(Map<String, dynamic> j) => Skill(
    id: _s(j['id']),
    skillKey: _s(j['skillKey'] ?? j['skill_key']),
    version: _i(j['version']) ?? 1,
    status: _s(j['status'], 'candidate'),
    preconditions: _map(j['preconditions']),
    validations: mapList(
      j['validations'],
    ).map(SkillValidation.fromJson).toList(),
  );

  final String id;
  final String skillKey;
  final int version;

  /// `candidate|validated|retired` (section 7).
  final String status;
  final Map<String, dynamic> preconditions;
  final List<SkillValidation> validations;

  SkillValidation? forEnv(String env) {
    for (final v in validations) {
      if (v.env == env) return v;
    }
    return null;
  }
}

class PrintJob {
  const PrintJob({
    required this.id,
    required this.state,
    required this.printerId,
    this.name = '',
    this.estTimeH,
    this.estFilamentG,
    this.estCostTry,
    this.qc,
  });

  factory PrintJob.fromJson(Map<String, dynamic> j) => PrintJob(
    id: _s(j['id'] ?? j['jobId']),
    state: _s(j['state'], 'queued'),
    printerId: _s(j['printerId'] ?? j['printer_id']),
    name: _s(j['name'] ?? j['artifact']),
    estTimeH: _d(j['estTimeH'] ?? j['est_time_h']),
    estFilamentG: _d(j['estFilamentG'] ?? j['est_filament_g']),
    estCostTry: _d(j['estCostTry'] ?? j['est_cost_try']),
    qc: j['qc'] == null ? null : _map(j['qc']),
  );

  final String id;

  /// `queued|printing|done|failed|cancelled` (section 7).
  final String state;
  final String printerId;
  final String name;
  final double? estTimeH;
  final double? estFilamentG;
  final double? estCostTry;
  final Map<String, dynamic>? qc;
}

/// `GET /printers/{id}/status` and the SignalR `PrintProgress` event.
class PrinterStatus {
  const PrinterStatus({
    required this.id,
    required this.state,
    this.nozzleC = 0,
    this.bedC = 0,
    this.targetNozzleC = 0,
    this.targetBedC = 0,
    this.pct = 0,
    this.layer = 0,
    this.etaMin = 0,
    this.jobName = '',
  });

  factory PrinterStatus.fromJson(Map<String, dynamic> j) => PrinterStatus(
    id: _s(j['id'] ?? j['printerId']),
    state: _s(j['state'], 'idle'),
    nozzleC: _d(j['nozzleC']) ?? 0,
    bedC: _d(j['bedC']) ?? 0,
    targetNozzleC: _d(j['targetNozzleC']) ?? 0,
    targetBedC: _d(j['targetBedC']) ?? 0,
    pct: _d(j['pct']) ?? 0,
    layer: _i(j['layer']) ?? 0,
    etaMin: _i(j['etaMin']) ?? 0,
    jobName: _s(j['jobName']),
  );

  final String id;
  final String state;
  final double nozzleC;
  final double bedC;
  final double targetNozzleC;
  final double targetBedC;
  final double pct;
  final int layer;
  final int etaMin;
  final String jobName;

  PrinterStatus mergeProgress(Map<String, dynamic> j) => PrinterStatus(
    id: id,
    state: 'printing',
    nozzleC: _d(j['nozzleC']) ?? nozzleC,
    bedC: _d(j['bedC']) ?? bedC,
    targetNozzleC: targetNozzleC,
    targetBedC: targetBedC,
    pct: _d(j['pct']) ?? pct,
    layer: _i(j['layer']) ?? layer,
    etaMin: _i(j['etaMin']) ?? etaMin,
    jobName: jobName,
  );
}

class AuditEntry {
  const AuditEntry({
    required this.ts,
    required this.actor,
    required this.action,
    this.target,
    this.outcome,
    this.durationMs,
    this.approvalId,
  });

  factory AuditEntry.fromJson(Map<String, dynamic> j) => AuditEntry(
    ts: _dt(j['ts']) ?? DateTime.now(),
    actor: _s(j['actor']),
    action: _s(j['action']),
    target: j['target'] == null ? null : _s(j['target']),
    outcome: j['outcome'] == null ? null : _s(j['outcome']),
    durationMs: _i(j['durationMs'] ?? j['duration_ms']),
    approvalId: j['approvalId'] == null ? null : _s(j['approvalId']),
  );

  final DateTime ts;

  /// `agent:mechanical` | `user:mg` (section 7).
  final String actor;
  final String action;
  final String? target;
  final String? outcome;
  final int? durationMs;
  final String? approvalId;

  bool get isToolCall => actor.startsWith('agent:');
  bool get isError => outcome == 'error' || outcome == 'failure';
}

/// One turn of the brain console (`POST /brain/command`, screen 6).
class BrainCommand {
  const BrainCommand({
    required this.id,
    required this.text,
    required this.state,
    this.intent,
    this.change,
    this.result,
    this.createdAt,
  });

  factory BrainCommand.fromJson(Map<String, dynamic> j) => BrainCommand(
    id: _s(j['id'] ?? j['commandId']),
    text: _s(j['text']),
    state: _s(j['state'], 'pending'),
    intent: j['intent'] == null ? null : _s(j['intent']),
    change: j['change'] == null ? null : _s(j['change']),
    result: j['result'] == null ? null : _map(j['result']),
    createdAt: _dt(j['createdAt']) ?? DateTime.now(),
  );

  final String id;
  final String text;

  /// `pending|delivered|applied|failed|rejected` (section 7 `commands`).
  final String state;
  final String? intent;
  final String? change;
  final Map<String, dynamic>? result;
  final DateTime? createdAt;

  BrainCommand mergeResult(BrainCommand other) => BrainCommand(
    id: id,
    text: text,
    state: other.state,
    intent: other.intent ?? intent,
    change: other.change ?? change,
    result: other.result ?? result,
    createdAt: createdAt,
  );
}

/// SignalR `Alert` event.
class Alert {
  const Alert({
    required this.severity,
    required this.code,
    required this.message,
    required this.ts,
  });

  factory Alert.fromJson(Map<String, dynamic> j) => Alert(
    severity: _s(j['severity'], 'info'),
    code: _s(j['code']),
    message: _s(j['message']),
    ts: _dt(j['ts']) ?? DateTime.now(),
  );

  final String severity;
  final String code;
  final String message;
  final DateTime ts;
}

/// A registered push device (`POST /auth/devices`), listed under Settings.
class DeviceSession {
  const DeviceSession({
    required this.id,
    required this.platform,
    this.lastSeen,
    this.current = false,
  });

  factory DeviceSession.fromJson(Map<String, dynamic> j) => DeviceSession(
    id: _s(j['id']),
    platform: _s(j['platform']),
    lastSeen: _dt(j['lastSeen'] ?? j['last_seen']),
    current: j['current'] == true,
  );

  final String id;
  final String platform;
  final DateTime? lastSeen;
  final bool current;
}
