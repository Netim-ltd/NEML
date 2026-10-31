// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:signalr_netcore/signalr_client.dart';

import '../auth/auth.dart';
import '../config.dart';
import '../network/online.dart';

/// Server to client events of `/hubs/live` (section 9.4), in spec order.
const kLiveEvents = <String>[
  'RobotState',
  'TelemetryTick',
  'TaskUpdated',
  'TaskRunEvent',
  'CampaignProgress',
  'ApprovalRequested',
  'ApprovalDecided',
  'PrintProgress',
  'BrainStatus',
  'Alert',
];

class LiveEvent {
  const LiveEvent(this.name, this.data);

  final String name;
  final Map<String, dynamic> data;
}

/// One SignalR connection for the whole app; screens filter [events] by name
/// and by the group they subscribed to.
class LiveClient {
  LiveClient({
    required this.serverUrl,
    required this.accessToken,
    this.onConnected,
    this.onDisconnected,
  });

  final String serverUrl;
  final Future<String> Function() accessToken;
  final void Function()? onConnected;
  final void Function()? onDisconnected;

  final _events = StreamController<LiveEvent>.broadcast();
  HubConnection? _hub;

  Stream<LiveEvent> get events => _events.stream;

  bool get connected => _hub?.state == HubConnectionState.Connected;

  Future<void> start() async {
    if (_hub != null) return;
    final hub = HubConnectionBuilder()
        .withUrl(
          '$serverUrl/hubs/live',
          options: HttpConnectionOptions(accessTokenFactory: accessToken),
        )
        .withAutomaticReconnect()
        .build();
    for (final name in kLiveEvents) {
      hub.on(name, (args) {
        final first = (args?.isNotEmpty ?? false) ? args!.first : null;
        _events.add(
          LiveEvent(
            name,
            first is Map
                ? first.map((k, v) => MapEntry('$k', v))
                : <String, dynamic>{},
          ),
        );
      });
    }
    hub.onclose(({Exception? error}) => onDisconnected?.call());
    hub.onreconnecting(({Exception? error}) => onDisconnected?.call());
    hub.onreconnected(({String? connectionId}) => onConnected?.call());
    _hub = hub;
    await hub.start();
    onConnected?.call();
  }

  Future<void> subscribeRobot(String robotId) async =>
      _hub?.invoke('SubscribeRobot', args: [robotId]);

  Future<void> subscribeCampaign(String campaignId) async =>
      _hub?.invoke('SubscribeCampaign', args: [campaignId]);

  Future<void> unsubscribeAll() async => _hub?.invoke('UnsubscribeAll');

  Future<void> dispose() async {
    await _hub?.stop();
    _hub = null;
    await _events.close();
  }
}

final liveClientProvider = Provider<LiveClient?>((ref) {
  final session = ref.watch(sessionProvider);
  if (session == null) return null;
  final serverUrl = ref.watch(settingsProvider.select((s) => s.serverUrl));
  final online = ref.read(onlineProvider.notifier);
  final client = LiveClient(
    serverUrl: serverUrl,
    accessToken: () async => ref.read(sessionProvider)?.access ?? '',
    onConnected: online.markOnline,
    onDisconnected: online.markOffline,
  );
  ref.onDispose(client.dispose);
  return client;
});

/// Hot stream of hub events. Nothing connects until something listens.
final liveEventsProvider = StreamProvider<LiveEvent>((ref) {
  final client = ref.watch(liveClientProvider);
  if (client == null) return const Stream<LiveEvent>.empty();
  unawaited(client.start().catchError((Object _) {}));
  return client.events;
});

/// Events of a single hub method, e.g. `ref.watch(liveEventProvider('Alert'))`.
final liveEventProvider = StreamProvider.family<LiveEvent, String>((ref, name) {
  final client = ref.watch(liveClientProvider);
  if (client == null) return const Stream<LiveEvent>.empty();
  unawaited(client.start().catchError((Object _) {}));
  return client.events.where((event) => event.name == name);
});
