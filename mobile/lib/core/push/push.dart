// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth.dart';
import '../config.dart';
import '../network/api.dart';

/// Push trigger table of section 10.4. `priority` is the Android importance
/// and `sound` the "Ses" column.
@immutable
class PushRule {
  const PushRule(this.trigger, this.importance, this.sound);

  final String trigger;
  final Importance importance;
  final bool sound;

  String get channelId => 'neml.$trigger';
}

const _rules = <String, PushRule>{
  // Onay istendi (seviye 3-4) | Yuksek | Var
  'approval_requested': PushRule(
    'approval_requested',
    Importance.high,
    true,
  ),
  // Robot fault / estop | Yuksek | Var
  'robot_fault': PushRule('robot_fault', Importance.high, true),
  // Gorev basarisiz (3. deneme) | Normal | Yok
  'task_failed': PushRule('task_failed', Importance.defaultImportance, false),
  // Kampanya tamamlandi | Normal | Yok
  'campaign_completed': PushRule(
    'campaign_completed',
    Importance.defaultImportance,
    false,
  ),
  // Baski bitti | Dusuk | Yok
  'print_finished': PushRule('print_finished', Importance.low, false),
  // Butce %90 | Normal | Yok
  'budget_90': PushRule('budget_90', Importance.defaultImportance, false),
};

PushRule ruleFor(String? trigger) =>
    _rules[trigger] ??
    const PushRule('other', Importance.defaultImportance, false);

/// FCM + local notifications wiring (section 10.4).
class PushService {
  PushService(this._ref);

  final Ref _ref;
  final _local = FlutterLocalNotificationsPlugin();

  Future<void> start() async {
    // Web push needs a separate Firebase web configuration and service worker.
    // The operator console remains usable without it.
    if (kIsWeb) return;
    await Firebase.initializeApp();
    await _local.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        iOS: DarwinInitializationSettings(),
      ),
    );
    final messaging = FirebaseMessaging.instance;
    await messaging.requestPermission();
    final token = await messaging.getToken();
    if (token != null) await _register(token);
    messaging.onTokenRefresh.listen(_register);
    FirebaseMessaging.onMessage.listen(show);
  }

  Future<void> _register(String token) async {
    final platform = defaultTargetPlatform == TargetPlatform.iOS ? 'ios' : 'android';
    try {
      await _ref.read(apiProvider).registerDevice(platform, token);
    } on Object {
      // The device row is re-registered on the next launch; not fatal.
    }
  }

  /// Renders a foreground message with the channel its trigger demands, and
  /// drops it if the operator muted that trigger in Settings.
  Future<void> show(RemoteMessage message) async {
    final trigger = message.data['trigger']?.toString();
    if (_ref.read(settingsProvider).mutedTriggers.contains(trigger)) return;
    final rule = ruleFor(trigger);
    await _local.show(
      id: message.messageId.hashCode,
      title: message.notification?.title ?? trigger ?? 'NEML',
      body: message.notification?.body ?? '',
      notificationDetails: NotificationDetails(
        android: AndroidNotificationDetails(
          rule.channelId,
          rule.trigger,
          importance: rule.importance,
          priority: rule.importance == Importance.high
              ? Priority.high
              : Priority.defaultPriority,
          playSound: rule.sound,
        ),
        iOS: DarwinNotificationDetails(presentSound: rule.sound),
      ),
      payload: message.data['route']?.toString(),
    );
  }
}

/// Started once, after sign-in, from the app shell.
final pushServiceProvider = Provider<PushService>(PushService.new);

final pushStartupProvider = FutureProvider<void>((ref) async {
  if (ref.watch(sessionProvider) == null) return;
  // ponytail: Firebase is optional in dev builds without google-services.json;
  // a failed init must not block the operator from seeing the lab.
  try {
    await ref.read(pushServiceProvider).start();
  } on Object {
    return;
  }
});
