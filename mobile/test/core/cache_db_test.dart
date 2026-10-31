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

void main() {
  setUpAll(() => registerFallbackValue(RequestOptions(path: '/')));

  late CacheDb db;

  setUp(() => db = CacheDb(NativeDatabase.memory()));
  tearDown(() => db.close());

  group('CacheDb', () {
    test('stores and reads back a body with its timestamp', () async {
      final at = DateTime(2026, 9, 15, 14, 5);
      await db.put('/robots', '[{"id":"R01"}]', at: at);

      final cached = await db.read('/robots');
      expect(cached, isNotNull);
      expect(cached!.body, '[{"id":"R01"}]');
      expect(cached.updatedAt, at);
      expect(await db.lastSync(), at);
    });

    test('a second write replaces the first', () async {
      await db.put('/robots', 'old', at: DateTime(2026, 9, 15, 10));
      await db.put('/robots', 'new', at: DateTime(2026, 9, 15, 11));
      expect((await db.read('/robots'))!.body, 'new');
    });

    test('an unknown key reads back null', () async {
      expect(await db.read('/nope'), isNull);
      expect(await db.lastSync(), isNull);
    });

    test('sign-out wipes cached operator data', () async {
      await db.put('/robots', 'x');
      await db.queueRejection('a1', 'no');
      await db.wipe();
      expect(await db.read('/robots'), isNull);
      expect(await db.pendingRejections(), isEmpty);
    });

    test('queued rejections are FIFO and individually clearable', () async {
      await db.queueRejection('a1', 'first');
      await db.queueRejection('a2', 'second');
      expect(
        (await db.pendingRejections()).map((r) => r.approvalId),
        ['a1', 'a2'],
      );
      await db.clearRejection('a1');
      expect((await db.pendingRejections()).single.approvalId, 'a2');
    });
  });

  group('CacheInterceptor read path (section 10.3)', () {
    late _MockAdapter adapter;
    late Dio dio;
    late DateTime? offlineSince;

    setUp(() {
      adapter = _MockAdapter();
      offlineSince = null;
      dio = Dio(BaseOptions(baseUrl: 'https://neml.test/api/v1'))
        ..httpClientAdapter = adapter
        ..interceptors.add(
          CacheInterceptor(
            db: db,
            markOnline: (_) {},
            markOffline: (lastSync) => offlineSince = lastSync,
          ),
        );
    });

    test('a successful GET is cached, then served when the link dies', () async {
      when(() => adapter.fetch(any(), any(), any())).thenAnswer(
        (_) async => ResponseBody.fromString(
          '{"items":[{"id":"R01"}]}',
          200,
          headers: {
            Headers.contentTypeHeader: [Headers.jsonContentType],
          },
        ),
      );
      await dio.get<dynamic>('/robots', queryParameters: {'page': 1});

      // A real adapter failure carries the options of the call that failed,
      // query string included — that is what the cache key is built from.
      when(() => adapter.fetch(any(), any(), any())).thenAnswer(
        (inv) async => throw DioException(
          requestOptions: inv.positionalArguments[0] as RequestOptions,
          type: DioExceptionType.connectionError,
        ),
      );
      final offline = await dio.get<dynamic>(
        '/robots',
        queryParameters: {'page': 1},
      );

      expect(offline.statusCode, 200);
      expect(offline.extra[kFromCache], isTrue);
      expect((offline.data as Map)['items'], isA<List<dynamic>>());
      expect(offlineSince, isNotNull, reason: 'banner needs the last sync time');
    });

    test('a GET with no cached copy still fails', () async {
      when(() => adapter.fetch(any(), any(), any())).thenThrow(
        DioException(
          requestOptions: RequestOptions(path: '/skills'),
          type: DioExceptionType.connectionError,
        ),
      );
      await expectLater(
        dio.get<dynamic>('/skills'),
        throwsA(isA<DioException>()),
      );
    });

    test('query order does not change the cache key', () {
      final a = RequestOptions(
        path: '/tasks',
        queryParameters: {'state': 'queued', 'kind': 'human'},
      );
      final b = RequestOptions(
        path: '/tasks',
        queryParameters: {'kind': 'human', 'state': 'queued'},
      );
      expect(cacheKeyFor(a), cacheKeyFor(b));
    });

    test('a blocked write is not mistaken for a network failure', () {
      final blocked = DioException(
        requestOptions: RequestOptions(path: '/tasks'),
        type: DioExceptionType.unknown,
        error: const OfflineWriteBlocked(),
      );
      expect(isNetworkFailure(blocked), isFalse);
    });
  });
}
