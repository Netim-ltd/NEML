// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'dart:convert';

import 'package:dio/dio.dart';

import '../db/cache_db.dart';
import '../models.dart';
import 'online.dart';

/// `RequestOptions.extra` flag set by exactly one call site —
/// `NemlApi.rejectApproval` — to opt a write into the offline queue.
const kQueueWhenOffline = 'neml.queueWhenOffline';

/// `RequestOptions.extra` flag marking the retry that follows a token refresh.
const kRefreshRetry = 'neml.refreshed';

/// Set on responses served from the drift cache instead of the network.
const kFromCache = 'neml.fromCache';

bool isNetworkFailure(DioException e) => switch (e.type) {
  DioExceptionType.connectionError ||
  DioExceptionType.connectionTimeout ||
  DioExceptionType.receiveTimeout ||
  DioExceptionType.sendTimeout => true,
  DioExceptionType.unknown => e.error is! OfflineWriteBlocked,
  _ => false,
};

/// Cache key for a GET: path plus its query, order-independent.
String cacheKeyFor(RequestOptions o) {
  final query = o.queryParameters.entries
      .map((e) => '${e.key}=${e.value}')
      .toList()
    ..sort();
  return query.isEmpty ? o.path : '${o.path}?${query.join('&')}';
}

/// Section 10.3, enforced in code at the single choke point every write goes
/// through. GETs pass (the cache interceptor answers them); writes are
/// rejected while offline; an approval rejection is queued instead.
class WriteGuardInterceptor extends Interceptor {
  WriteGuardInterceptor({required this.isOnline, required this.queueRejection});

  final bool Function() isOnline;
  final Future<void> Function(RequestOptions options) queueRejection;

  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    if (options.method.toUpperCase() == 'GET' || isOnline()) {
      handler.next(options);
      return;
    }
    if (options.extra[kQueueWhenOffline] == true) {
      await queueRejection(options);
      handler.reject(
        DioException(
          requestOptions: options,
          type: DioExceptionType.cancel,
          error: const OfflineRejectionQueued(),
        ),
      );
      return;
    }
    handler.reject(
      DioException(
        requestOptions: options,
        type: DioExceptionType.cancel,
        error: const OfflineWriteBlocked(),
      ),
    );
  }
}

/// Attaches the access token and, on a 401, rotates the refresh token once
/// (section 5.5: 15 min access, 30 day rotating refresh).
///
/// Deliberately a plain [Interceptor], not a `QueuedInterceptor`: the replay
/// below runs through the same dio instance, so a second 401 would re-enter
/// this interceptor and deadlock behind the task still awaiting it.
/// Concurrent 401s are instead de-duplicated by [_refreshing].
class AuthInterceptor extends Interceptor {
  AuthInterceptor({
    required this.session,
    required this.refreshCall,
    required this.retry,
    required this.onRefreshed,
    required this.onSignOut,
  });

  final Session? Function() session;
  final Future<Session?> Function(String refreshToken) refreshCall;
  final Future<Response<dynamic>> Function(RequestOptions options) retry;
  final void Function(Session session) onRefreshed;
  final void Function() onSignOut;

  /// The one rotation in flight, shared by every request that hit a 401 at the
  /// same time. Refresh tokens rotate (section 5.5), so a second concurrent
  /// call would spend a token that is already dead and sign the operator out
  /// for nothing.
  Future<Session?>? _refreshing;

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    final current = session();
    if (current != null && current.access.isNotEmpty) {
      options.headers['Authorization'] = 'Bearer ${current.access}';
    }
    handler.next(options);
  }

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    final options = err.requestOptions;
    final current = session();
    if (err.response?.statusCode != 401 ||
        options.extra[kRefreshRetry] == true ||
        current == null ||
        current.refresh.isEmpty) {
      handler.next(err);
      return;
    }

    Session? rotated;
    try {
      rotated = await (_refreshing ??= refreshCall(
        current.refresh,
      ).whenComplete(() => _refreshing = null));
    } on Object {
      rotated = null;
    }
    if (rotated == null) {
      onSignOut();
      handler.next(err);
      return;
    }
    onRefreshed(rotated);

    options.extra[kRefreshRetry] = true;
    options.headers['Authorization'] = 'Bearer ${rotated.access}';
    try {
      handler.resolve(await retry(options));
    } on DioException catch (e) {
      handler.next(e);
    }
  }
}

/// Writes every successful GET into drift and serves it back when the network
/// is gone, so the app opens on the last known state instantly (section 10.3).
class CacheInterceptor extends Interceptor {
  CacheInterceptor({
    required this.db,
    required this.markOnline,
    required this.markOffline,
  });

  final CacheDb db;
  final void Function(DateTime at) markOnline;
  final void Function(DateTime? lastSync) markOffline;

  @override
  Future<void> onResponse(
    Response<dynamic> response,
    ResponseInterceptorHandler handler,
  ) async {
    final now = DateTime.now();
    markOnline(now);
    if (response.requestOptions.method.toUpperCase() == 'GET' &&
        response.data != null) {
      await db.put(
        cacheKeyFor(response.requestOptions),
        jsonEncode(response.data),
        at: now,
      );
    }
    handler.next(response);
  }

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    if (!isNetworkFailure(err)) {
      handler.next(err);
      return;
    }
    final options = err.requestOptions;
    if (options.method.toUpperCase() != 'GET') {
      markOffline(await db.lastSync());
      handler.next(err);
      return;
    }
    final cached = await db.read(cacheKeyFor(options));
    markOffline(cached?.updatedAt ?? await db.lastSync());
    if (cached == null) {
      handler.next(err);
      return;
    }
    handler.resolve(
      Response<dynamic>(
        requestOptions: options,
        statusCode: 200,
        data: jsonDecode(cached.body),
        extra: {kFromCache: true, 'updatedAt': cached.updatedAt},
      ),
    );
  }
}
