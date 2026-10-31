// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:neml_mobile/core/models.dart';
import 'package:neml_mobile/core/network/interceptors.dart';

class _MockAdapter extends Mock implements HttpClientAdapter {}

ResponseBody _json(String body, int status) => ResponseBody.fromString(
  body,
  status,
  headers: {
    Headers.contentTypeHeader: [Headers.jsonContentType],
  },
);

void main() {
  setUpAll(() => registerFallbackValue(RequestOptions(path: '/')));

  late _MockAdapter adapter;
  late Dio dio;
  late Session current;
  late List<String?> authHeaders;
  late int refreshCalls;
  late int signOuts;

  late Session? refreshResult;

  setUp(() {
    refreshResult = const Session(
      access: 'new-access',
      refresh: 'new-refresh',
      email: 'mg@neml',
      role: 'owner',
    );
    adapter = _MockAdapter();
    authHeaders = [];
    refreshCalls = 0;
    signOuts = 0;
    current = const Session(
      access: 'old-access',
      refresh: 'old-refresh',
      email: 'mg@neml',
      role: 'owner',
    );
    dio = Dio(BaseOptions(baseUrl: 'https://neml.test/api/v1'))
      ..httpClientAdapter = adapter;
    dio.interceptors.add(
      AuthInterceptor(
        session: () => current,
        refreshCall: (token) async {
          refreshCalls++;
          expect(token, 'old-refresh');
          return refreshResult;
        },
        retry: dio.fetch<dynamic>,
        onRefreshed: (s) => current = s,
        onSignOut: () => signOuts++,
      ),
    );
  });

  test('attaches the bearer token from the current session', () async {
    when(() => adapter.fetch(any(), any(), any())).thenAnswer((inv) async {
      authHeaders.add(
        (inv.positionalArguments[0] as RequestOptions)
            .headers['Authorization']
            ?.toString(),
      );
      return _json('{"ok":true}', 200);
    });

    await dio.get<dynamic>('/robots');
    expect(authHeaders, ['Bearer old-access']);
    expect(refreshCalls, 0);
  });

  test('rotates the refresh token once on 401 and replays the call', () async {
    var calls = 0;
    when(() => adapter.fetch(any(), any(), any())).thenAnswer((inv) async {
      calls++;
      authHeaders.add(
        (inv.positionalArguments[0] as RequestOptions)
            .headers['Authorization']
            ?.toString(),
      );
      return calls == 1
          ? _json('{"error":"expired"}', 401)
          : _json('{"items":[]}', 200);
    });

    final response = await dio.get<dynamic>('/robots');

    expect(response.statusCode, 200);
    expect(refreshCalls, 1);
    expect(authHeaders, ['Bearer old-access', 'Bearer new-access']);
    expect(current.access, 'new-access', reason: 'rotation is persisted');
    expect(signOuts, 0);
  });

  test('does not loop: a second 401 after the retry signs nothing out twice',
      () async {
    when(
      () => adapter.fetch(any(), any(), any()),
    ).thenAnswer((_) async => _json('{"error":"expired"}', 401));

    await expectLater(
      dio.get<dynamic>('/robots'),
      throwsA(
        isA<DioException>().having((e) => e.response?.statusCode, 'status', 401),
      ),
    );
    expect(refreshCalls, 1, reason: 'the replay is marked and never refreshed again');
  });

  test('a dead refresh token signs the operator out', () async {
    refreshResult = null;
    when(
      () => adapter.fetch(any(), any(), any()),
    ).thenAnswer((_) async => _json('{"error":"expired"}', 401));

    await expectLater(dio.get<dynamic>('/robots'), throwsA(isA<DioException>()));
    expect(signOuts, 1);
  });
}
