// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:drift/drift.dart';
import 'package:drift_flutter/drift_flutter.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Offline cache for section 10.3: the last successful GET body per endpoint,
/// plus the single class of write that is allowed to survive being offline —
/// an approval *rejection*.
///
/// ponytail: two hand-written tables driven by `customStatement`, so drift
/// needs no build_runner step here. Move to generated table classes if the
/// cache ever needs typed columns or joins.
class CacheDb extends GeneratedDatabase {
  CacheDb(super.executor);

  @override
  Iterable<TableInfo<Table, dynamic>> get allTables => const [];

  @override
  int get schemaVersion => 1;

  @override
  MigrationStrategy get migration => MigrationStrategy(
    onCreate: (m) async {
      await customStatement(
        'CREATE TABLE api_cache ('
        'key TEXT NOT NULL PRIMARY KEY, '
        'body TEXT NOT NULL, '
        'updated_at INTEGER NOT NULL)',
      );
      await customStatement(
        'CREATE TABLE pending_rejection ('
        'approval_id TEXT NOT NULL PRIMARY KEY, '
        'note TEXT NOT NULL, '
        'queued_at INTEGER NOT NULL)',
      );
    },
  );

  Future<void> put(String key, String body, {DateTime? at}) => customInsert(
    'INSERT INTO api_cache (key, body, updated_at) VALUES (?, ?, ?) '
    'ON CONFLICT(key) DO UPDATE SET body = excluded.body, '
    'updated_at = excluded.updated_at',
    variables: [
      Variable<String>(key),
      Variable<String>(body),
      Variable<int>((at ?? DateTime.now()).millisecondsSinceEpoch),
    ],
  );

  Future<CachedBody?> read(String key) async {
    final rows = await customSelect(
      'SELECT body, updated_at FROM api_cache WHERE key = ?',
      variables: [Variable<String>(key)],
    ).get();
    if (rows.isEmpty) return null;
    final row = rows.first;
    return CachedBody(
      row.read<String>('body'),
      DateTime.fromMillisecondsSinceEpoch(row.read<int>('updated_at')),
    );
  }

  /// Newest cache timestamp across all endpoints — drives the
  /// "cevrimdisi - son guncelleme HH:mm" banner.
  Future<DateTime?> lastSync() async {
    final rows = await customSelect(
      'SELECT MAX(updated_at) AS m FROM api_cache',
    ).get();
    final value = rows.isEmpty ? null : rows.first.read<int?>('m');
    return value == null ? null : DateTime.fromMillisecondsSinceEpoch(value);
  }

  /// Section 10.3: a rejection errs on the safe side, so it — and only it —
  /// may wait in this table until the network comes back.
  Future<void> queueRejection(String approvalId, String note) => customInsert(
    'INSERT INTO pending_rejection (approval_id, note, queued_at) '
    'VALUES (?, ?, ?) ON CONFLICT(approval_id) DO UPDATE SET '
    'note = excluded.note',
    variables: [
      Variable<String>(approvalId),
      Variable<String>(note),
      Variable<int>(DateTime.now().millisecondsSinceEpoch),
    ],
  );

  Future<List<PendingRejection>> pendingRejections() async {
    final rows = await customSelect(
      'SELECT approval_id, note FROM pending_rejection ORDER BY queued_at',
    ).get();
    return [
      for (final r in rows)
        PendingRejection(r.read<String>('approval_id'), r.read<String>('note')),
    ];
  }

  Future<void> clearRejection(String approvalId) => customUpdate(
    'DELETE FROM pending_rejection WHERE approval_id = ?',
    variables: [Variable<String>(approvalId)],
    updateKind: UpdateKind.delete,
  );

  /// Called on sign-out: cached operator data must not outlive the session.
  Future<void> wipe() async {
    await customStatement('DELETE FROM api_cache');
    await customStatement('DELETE FROM pending_rejection');
  }
}

class CachedBody {
  const CachedBody(this.body, this.updatedAt);

  final String body;
  final DateTime updatedAt;
}

class PendingRejection {
  const PendingRejection(this.approvalId, this.note);

  final String approvalId;
  final String note;
}

final cacheDbProvider = Provider<CacheDb>((ref) {
  final db = CacheDb(driftDatabase(
    name: 'neml_cache',
    web: DriftWebOptions(
      sqlite3Wasm: Uri.parse('sqlite3.wasm'),
      driftWorker: Uri.parse('drift_worker.js'),
    ),
  ));
  ref.onDispose(db.close);
  return db;
});
