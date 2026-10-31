// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'core/auth/token_store.dart';
import 'core/config.dart';
import 'core/push/push.dart';
import 'core/router/router.dart';
import 'core/theme/theme.dart';
import 'features/approvals/approvals_provider.dart';
import 'l10n/app_localizations.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Settings are read before the first frame so the app opens on the right
  // server, theme and language instead of flashing the defaults.
  final settings = await loadSettings(TokenStore(const FlutterSecureStorage()));
  runApp(
    ProviderScope(
      overrides: [settingsProvider.overrideWith(() => SettingsNotifier(settings))],
      child: const NemlApp(),
    ),
  );
}

class NemlApp extends ConsumerWidget {
  const NemlApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsProvider);
    // Side-effect providers that must live as long as the app does.
    ref.watch(pushStartupProvider);
    ref.watch(rejectionFlusherProvider);

    return MaterialApp.router(
      onGenerateTitle: (context) => AppLocalizations.of(context)!.appTitle,
      debugShowCheckedModeBanner: false,
      theme: nemlLightTheme,
      darkTheme: nemlDarkTheme,
      themeMode: settings.themeMode,
      locale: Locale(settings.localeCode),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      routerConfig: ref.watch(routerProvider),
    );
  }
}
