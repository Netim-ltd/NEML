// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:dio/dio.dart';
import 'package:dio_smart_retry/dio_smart_retry.dart';
import 'package:drift/native.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neml_mobile/core/auth/auth.dart';
import 'package:neml_mobile/core/config.dart';
import 'package:neml_mobile/core/db/cache_db.dart';
import 'package:neml_mobile/core/network/dio_client.dart';
import 'package:neml_mobile/core/network/interceptors.dart';
import 'package:neml_mobile/core/network/online.dart';

import '../helpers.dart';

/// The wiring of `dioProvider`: base URL, interceptor order and the retry
/// policy of section 10.3.
void main() {
  late CacheDb db;
  late ProviderContainer container;

  ProviderContainer build({
    String serverUrl = 'https://neml.test',
    bool online = true,
  }) {
    final c = ProviderContainer(
      overrides: [
        cacheDbProvider.overrideWithValue(db),
        authProvider.overrideWith(() => FakeAuth(testSession)),
        settingsProvider.overrideWith(
          () => SettingsNotifier(AppSettings(serverUrl: serverUrl)),
        ),
        if (!online)
          onlineProvider.overrideWith(
            () => FakeOnline(const ConnStatus(online: false)),
          ),
      ],
    );
    addTearDown(c.dispose);
    return c;
  }

  setUp(() {
    db = CacheDb(NativeDatabase.memory());
    addTearDown(db.close);
    container = build();
  });

  test('the base URL is the operator server plus the section 9.3 prefix', () {
    expect(kApiPrefix, '/api/v1');
    expect(
      container.read(dioProvider).options.baseUrl,
      'https://neml.test/api/v1',
    );
    expect(
      build(serverUrl: 'http://10.0.0.5:5000').read(dioProvider).options.baseUrl,
      'http://10.0.0.5:5000/api/v1',
    );
  });

  test('the refresh client carries no auth interceptor', () {
    // A 401 on the refresh call itself must not recurse into a refresh.
    final refresh = buildRefreshDio('https://neml.test');
    expect(refresh.options.baseUrl, 'https://neml.test/api/v1');
    expect(refresh.interceptors.whereType<AuthInterceptor>(), isEmpty);
  });

  test('interceptors run in the order section 10.3 needs', () {
    final interceptors = container.read(dioProvider).interceptors;
    // The write guard sees the request before the token is even attached, so
    // an offline write never reaches the wire.
    expect(interceptors.whereType<WriteGuardInterceptor>(), hasLength(1));
    expect(interceptors.whereType<AuthInterceptor>(), hasLength(1));
    expect(interceptors.whereType<RetryInterceptor>(), hasLength(1));
    expect(interceptors.whereType<CacheInterceptor>(), hasLength(1));
    expect(
      interceptors.indexWhere((i) => i is WriteGuardInterceptor),
      lessThan(interceptors.indexWhere((i) => i is AuthInterceptor)),
    );
  });

  group('retryGetOnly', () {
    DioException failure(String method, DioExceptionType type) => DioException(
      requestOptions: RequestOptions(path: '/tasks', method: method),
      type: type,
    );

    test('a dropped GET is retried', () async {
      expect(
        await retryGetOnly(failure('get', DioExceptionType.connectionError), 1),
        isTrue,
      );
    });

    test('a POST is never replayed', () async {
      // Replaying a write could deliver the same command to a robot twice.
      for (final method in const ['POST', 'PATCH', 'DELETE']) {
        expect(
          await retryGetOnly(
            failure(method, DioExceptionType.connectionError),
            1,
          ),
          isFalse,
          reason: method,
        );
      }
    });

    test('a server answer is not a network failure', () async {
      expect(
        await retryGetOnly(failure('GET', DioExceptionType.badResponse), 1),
        isFalse,
      );
    });
  });

  test('an offline write is blocked and a rejection is queued instead',
      () async {
    final offline = build(online: false);
    final dio = offline.read(dioProvider)
      ..httpClientAdapter = FakeHttp();

    await expectLater(
      dio.post<void>('/robots/R01/estop'),
      throwsA(
        isA<DioException>().having((e) => e.error, 'error',
            isA<OfflineWriteBlocked>()),
      ),
    );

    await expectLater(
      dio.post<void>(
        '/approvals/A1/reject',
        data: const {'note': 'guvenli degil'},
        options: Options(extra: const {kQueueWhenOffline: true}),
      ),
      throwsA(
        isA<DioException>().having((e) => e.error, 'error',
            isA<OfflineRejectionQueued>()),
      ),
    );

    final queued = await db.pendingRejections();
    expect(queued.single.approvalId, 'A1');
    expect(queued.single.note, 'guvenli degil');
  });

  test('a successful GET is cached and marks the app online', () async {
    final dio = container.read(dioProvider)..httpClientAdapter = FakeHttp();

    final response = await dio.get<dynamic>('/robots');

    expect(response.statusCode, 200);
    expect(await db.read('/robots'), isNotNull);
    expect(container.read(onlineProvider).online, isTrue);
  });
}
