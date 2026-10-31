// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:dio/dio.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:neml_mobile/core/db/cache_db.dart';
import 'package:neml_mobile/core/network/interceptors.dart';
import 'package:neml_mobile/core/network/online.dart';

class _MockAdapter extends Mock implements HttpClientAdapter {}

/// Section 10.3 in one file: offline writes are blocked and NOT queued,
/// because a command that reaches a robot late is dangerous. The single
/// exception is an approval rejection, which errs on the safe side.
void main() {
  setUpAll(() => registerFallbackValue(RequestOptions(path: '/')));

  late CacheDb db;
  late _MockAdapter adapter;
  late Dio dio;
  var online = false;

  setUp(() {
    db = CacheDb(NativeDatabase.memory());
    adapter = _MockAdapter();
    online = false;
    dio = Dio(BaseOptions(baseUrl: 'https://neml.test/api/v1'))
      ..httpClientAdapter = adapter
      ..interceptors.add(
        WriteGuardInterceptor(
          isOnline: () => online,
          queueRejection: (options) => db.queueRejection(
            options.path.split('/')[2],
            '${(options.data as Map)['note']}',
          ),
        ),
      );
    when(() => adapter.fetch(any(), any(), any())).thenAnswer(
      (_) async => ResponseBody.fromString(
        '{}',
        200,
        headers: {
          Headers.contentTypeHeader: [Headers.jsonContentType],
        },
      ),
    );
  });

  tearDown(() => db.close());

  test('an offline e-stop is blocked, never queued', () async {
    await expectLater(
      dio.post<dynamic>('/robots/R01/estop'),
      throwsA(
        isA<DioException>().having(
          (e) => e.error,
          'error',
          isA<OfflineWriteBlocked>(),
        ),
      ),
    );
    verifyNever(() => adapter.fetch(any(), any(), any()));
    expect(await db.pendingRejections(), isEmpty);
  });

  test('an offline task creation is blocked too', () async {
    await expectLater(
      dio.post<dynamic>('/tasks', data: {'title': 'x'}),
      throwsA(
        isA<DioException>().having(
          (e) => e.error,
          'error',
          isA<OfflineWriteBlocked>(),
        ),
      ),
    );
    expect(await db.pendingRejections(), isEmpty);
  });

  test('an offline approval REJECTION is queued instead', () async {
    await expectLater(
      dio.post<dynamic>(
        '/approvals/a-42/reject',
        data: const {'note': 'guvenli degil'},
        options: Options(extra: const {kQueueWhenOffline: true}),
      ),
      throwsA(
        isA<DioException>().having(
          (e) => e.error,
          'error',
          isA<OfflineRejectionQueued>(),
        ),
      ),
    );
    final queued = await db.pendingRejections();
    expect(queued.single.approvalId, 'a-42');
    expect(queued.single.note, 'guvenli degil');
    verifyNever(() => adapter.fetch(any(), any(), any()));
  });

  test('an offline approval APPROVAL is still blocked', () async {
    await expectLater(
      dio.post<dynamic>('/approvals/a-42/approve', data: const {'note': ''}),
      throwsA(
        isA<DioException>().having(
          (e) => e.error,
          'error',
          isA<OfflineWriteBlocked>(),
        ),
      ),
    );
    expect(await db.pendingRejections(), isEmpty);
  });

  test('reads are never blocked - they fall through to the cache', () async {
    final res = await dio.get<dynamic>('/robots');
    expect(res.statusCode, 200);
  });

  test('online writes pass straight through', () async {
    online = true;
    final res = await dio.post<dynamic>('/robots/R01/estop');
    expect(res.statusCode, 200);
    verify(() => adapter.fetch(any(), any(), any())).called(1);
  });
}
