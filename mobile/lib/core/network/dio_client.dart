// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:dio/dio.dart';
import 'package:dio_smart_retry/dio_smart_retry.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth.dart';
import '../config.dart';
import '../db/cache_db.dart';
import '../models.dart';
import 'interceptors.dart';
import 'online.dart';

/// Base path of the remote API (section 9.3).
const kApiPrefix = '/api/v1';

/// Bare client used only to rotate the refresh token: it must not carry the
/// auth interceptor, or a 401 would recurse.
Dio buildRefreshDio(String serverUrl) => Dio(
  BaseOptions(
    baseUrl: '$serverUrl$kApiPrefix',
    connectTimeout: const Duration(seconds: 10),
    receiveTimeout: const Duration(seconds: 20),
    contentType: Headers.jsonContentType,
  ),
);

/// Only GETs are retried. Replaying a POST could deliver the same command to a
/// robot twice, which section 10.3 treats as a hazard, not an inconvenience.
Future<bool> retryGetOnly(DioException error, int attempt) async =>
    error.requestOptions.method.toUpperCase() == 'GET' &&
    isNetworkFailure(error);

final dioProvider = Provider<Dio>((ref) {
  final serverUrl = ref.watch(settingsProvider.select((s) => s.serverUrl));
  final db = ref.watch(cacheDbProvider);
  final refreshDio = buildRefreshDio(serverUrl);

  final dio = Dio(
    BaseOptions(
      baseUrl: '$serverUrl$kApiPrefix',
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 20),
      contentType: Headers.jsonContentType,
    ),
  );

  dio.interceptors.addAll([
    WriteGuardInterceptor(
      isOnline: () => ref.read(onlineProvider).online,
      queueRejection: (options) {
        final approvalId = options.path.split('/')[2];
        final note = options.data is Map
            ? '${(options.data as Map)['note'] ?? ''}'
            : '';
        return db.queueRejection(approvalId, note);
      },
    ),
    AuthInterceptor(
      session: () => ref.read(authProvider).value,
      refreshCall: (refreshToken) async {
        final res = await refreshDio.post<Map<String, dynamic>>(
          '/auth/refresh',
          data: {'refresh': refreshToken},
        );
        final body = res.data;
        return body == null ? null : Session.fromJson(body);
      },
      retry: (options) => dio.fetch<dynamic>(options),
      onRefreshed: (session) =>
          ref.read(authProvider.notifier).applyRefreshed(session),
      onSignOut: () => ref.read(authProvider.notifier).signOut(),
    ),
    RetryInterceptor(dio: dio, retries: 2, retryEvaluator: retryGetOnly),
    CacheInterceptor(
      db: db,
      markOnline: (at) => ref.read(onlineProvider.notifier).markOnline(at),
      markOffline: (lastSync) =>
          ref.read(onlineProvider.notifier).markOffline(lastSync),
    ),
  ]);

  ref.onDispose(dio.close);
  return dio;
});
