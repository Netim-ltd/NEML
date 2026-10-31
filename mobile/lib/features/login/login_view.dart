// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config.dart';
import '../../shared/widgets.dart';
import 'login_provider.dart';

class LoginView extends ConsumerStatefulWidget {
  const LoginView({super.key});

  @override
  ConsumerState<LoginView> createState() => _LoginViewState();
}

class _LoginViewState extends ConsumerState<LoginView> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  late final _server = TextEditingController(
    text: ref.read(settingsProvider).serverUrl,
  );

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _server.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final controller = ref.read(loginControllerProvider.notifier);
    await controller.setServer(_server.text);
    await controller.submit(_email.text, _password.text);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = tr(context);
    final settings = ref.watch(settingsProvider);
    final state = ref.watch(loginControllerProvider);

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    l10n.appTitle,
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 24),
                  TextField(
                    key: const Key('login-email'),
                    controller: _email,
                    keyboardType: TextInputType.emailAddress,
                    autofillHints: const [AutofillHints.email],
                    decoration: InputDecoration(labelText: l10n.email),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    key: const Key('login-password'),
                    controller: _password,
                    obscureText: true,
                    onSubmitted: (_) => _submit(),
                    decoration: InputDecoration(labelText: l10n.password),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    key: const Key('login-server'),
                    controller: _server,
                    keyboardType: TextInputType.url,
                    decoration: InputDecoration(labelText: l10n.serverAddress),
                  ),
                  SwitchListTile(
                    key: const Key('login-biometric'),
                    contentPadding: EdgeInsets.zero,
                    value: settings.biometricLock,
                    title: Text(l10n.biometricLock),
                    subtitle: Text(l10n.biometricLockHint),
                    onChanged: (v) => ref
                        .read(loginControllerProvider.notifier)
                        .setBiometricLock(v),
                  ),
                  const SizedBox(height: 12),
                  if (state.hasError)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Text(
                        '${l10n.loginFailed}: ${state.error}',
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ),
                  FilledButton(
                    key: const Key('login-submit'),
                    onPressed: state.isLoading ? null : _submit,
                    child: state.isLoading
                        ? const SizedBox(
                            height: 18,
                            width: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : Text(l10n.signIn),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
