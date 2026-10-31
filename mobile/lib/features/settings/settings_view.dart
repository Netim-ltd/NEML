// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/auth/auth.dart';
import '../../core/config.dart';
import '../../core/models.dart';
import '../../l10n/app_localizations.dart';
import '../../shared/widgets.dart';
import 'settings_provider.dart';

/// Section 10.2 screen 13 — server, notification preferences, theme, language,
/// sessions, sign out.
class SettingsView extends ConsumerWidget {
  const SettingsView({super.key});

  String _triggerLabel(AppLocalizations l10n, String trigger) =>
      switch (trigger) {
        'approval_requested' => l10n.pushApprovalRequested,
        'robot_fault' => l10n.pushRobotFault,
        'task_failed' => l10n.pushTaskFailed,
        'campaign_completed' => l10n.pushCampaignCompleted,
        'print_finished' => l10n.pushPrintFinished,
        _ => l10n.pushBudget90,
      };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final settings = ref.watch(settingsProvider);
    final notifier = ref.read(settingsProvider.notifier);
    final session = ref.watch(sessionProvider);
    final devices = ref.watch(devicesProvider);

    return NemlScaffold(
      title: l10n.settings,
      body: ListView(
        children: [
          ListTile(
            leading: const Icon(Icons.dns_outlined),
            title: Text(l10n.serverAddress),
            subtitle: Text(settings.serverUrl),
            onTap: () => _editServer(context, ref, settings),
          ),
          SwitchListTile(
            secondary: const Icon(Icons.fingerprint),
            value: settings.biometricLock,
            title: Text(l10n.biometricLock),
            subtitle: Text(l10n.biometricLockHint),
            onChanged: (v) =>
                notifier.update(settings.copyWith(biometricLock: v)),
          ),
          ListTile(
            key: const Key('model-settings'),
            leading: const Icon(Icons.tune),
            title: Text(
              Localizations.localeOf(context).languageCode == 'tr'
                  ? 'Robot modeli ayarları'
                  : 'Robot model settings',
            ),
            subtitle: Text(
              Localizations.localeOf(context).languageCode == 'tr'
                  ? 'MTBF, bakım aralığı, filament fiyatı'
                  : 'MTBF, service interval, filament price',
            ),
            onTap: () => context.push('/settings/models'),
          ),
          const Divider(),
          ListTile(title: Text(l10n.notifications)),
          for (final trigger in kPushTriggers)
            SwitchListTile(
              key: Key('push-$trigger'),
              value: !settings.mutedTriggers.contains(trigger),
              title: Text(_triggerLabel(l10n, trigger)),
              onChanged: (v) => notifier.toggleTrigger(trigger, v),
            ),
          const Divider(),
          ListTile(title: Text(l10n.theme)),
          for (final mode in ThemeMode.values)
            ListTile(
              title: Text(switch (mode) {
                ThemeMode.dark => l10n.themeDark,
                ThemeMode.light => l10n.themeLight,
                ThemeMode.system => l10n.themeSystem,
              }),
              trailing: settings.themeMode == mode
                  ? const Icon(Icons.check)
                  : null,
              onTap: () => notifier.update(settings.copyWith(themeMode: mode)),
            ),
          const Divider(),
          ListTile(title: Text(l10n.language)),
          for (final code in const ['tr', 'en'])
            ListTile(
              key: Key('language-$code'),
              title: Text(code == 'tr' ? l10n.turkish : l10n.english),
              trailing: settings.localeCode == code
                  ? const Icon(Icons.check)
                  : null,
              onTap: () => notifier.update(settings.copyWith(localeCode: code)),
            ),
          const Divider(),
          ListTile(title: Text(l10n.sessions), subtitle: Text(session?.email ?? '')),
          AsyncView<List<DeviceSession>>(
            devices,
            onRetry: () => ref.invalidate(devicesProvider),
            builder: (items) => Column(
              children: [
                if (items.isEmpty) ListTile(title: Text(l10n.empty)),
                for (final d in items)
                  ListTile(
                    leading: const Icon(Icons.phone_iphone),
                    title: Text(d.platform),
                    subtitle: Text(
                      d.lastSeen == null ? '' : dayTime.format(d.lastSeen!),
                    ),
                    trailing: d.current ? const Icon(Icons.check) : null,
                  ),
              ],
            ),
          ),
          const Divider(),
          ListTile(
            key: const Key('sign-out'),
            leading: const Icon(Icons.logout),
            title: Text(l10n.signOut),
            onTap: () => ref.read(authProvider.notifier).signOut(),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  Future<void> _editServer(
    BuildContext context,
    WidgetRef ref,
    AppSettings settings,
  ) async {
    final l10n = tr(context);
    final controller = TextEditingController(text: settings.serverUrl);
    final value = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(l10n.serverAddress),
        content: TextField(controller: controller, autofocus: true),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: Text(l10n.cancel),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, controller.text),
            child: Text(l10n.save),
          ),
        ],
      ),
    );
    controller.dispose();
    if (value != null && value.trim().isNotEmpty) {
      await ref
          .read(settingsProvider.notifier)
          .update(settings.copyWith(serverUrl: value.trim()));
    }
  }
}
