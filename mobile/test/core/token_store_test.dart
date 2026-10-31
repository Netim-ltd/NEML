// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:neml_mobile/core/auth/token_store.dart';

import '../helpers.dart';

class _MockStorage extends Mock implements FlutterSecureStorage {}

/// Keychain/Keystore handling of section 5.5. With the biometric lock on, the
/// session is written behind a user-presence constraint, which is what makes
/// the cold-start read prompt for Face ID / fingerprint.
void main() {
  late _MockStorage storage;
  late TokenStore store;

  setUp(() {
    storage = _MockStorage();
    store = TokenStore(storage);
    when(
      () => storage.write(
        key: any(named: 'key'),
        value: any(named: 'value'),
        aOptions: any(named: 'aOptions'),
        iOptions: any(named: 'iOptions'),
        mOptions: any(named: 'mOptions'),
      ),
    ).thenAnswer((_) async {});
    when(() => storage.delete(key: any(named: 'key'))).thenAnswer((_) async {});
  });

  void stubRead(String? raw) => when(
    () => storage.read(
      key: any(named: 'key'),
      aOptions: any(named: 'aOptions'),
      iOptions: any(named: 'iOptions'),
      mOptions: any(named: 'mOptions'),
    ),
  ).thenAnswer((_) async => raw);

  test('a stored session round-trips', () async {
    stubRead(jsonEncode(testSession.toJson()));
    final session = await store.read(biometric: false);
    expect(session?.access, 'access-token');
    expect(session?.role, 'owner');
    verify(
      () => storage.read(
        key: TokenStore.sessionKey,
        aOptions: null,
        iOptions: null,
        mOptions: null,
      ),
    ).called(1);
  });

  test('no stored session means signed out', () async {
    stubRead(null);
    expect(await store.read(biometric: true), isNull);
  });

  test('a corrupted blob is treated as signed out, not as a crash', () async {
    stubRead('not json');
    expect(await store.read(biometric: false), isNull);
  });

  test('the biometric lock adds the user-presence constraint', () async {
    stubRead(null);
    await store.read(biometric: true);
    final read = verify(
      () => storage.read(
        key: TokenStore.sessionKey,
        aOptions: captureAny(named: 'aOptions'),
        iOptions: captureAny(named: 'iOptions'),
        mOptions: any(named: 'mOptions'),
      ),
    ).captured;
    expect(read[0], isA<AndroidOptions>());
    expect(read[1], isA<IOSOptions>());

    await store.save(testSession, biometric: true);
    final written = verify(
      () => storage.write(
        key: TokenStore.sessionKey,
        value: captureAny(named: 'value'),
        aOptions: captureAny(named: 'aOptions'),
        iOptions: any(named: 'iOptions'),
        mOptions: any(named: 'mOptions'),
      ),
    ).captured;
    expect(jsonDecode(written[0] as String), testSession.toJson());
    expect(written[1], isA<AndroidOptions>());
  });

  test('without the lock the session is written unconstrained', () async {
    await store.save(testSession, biometric: false);
    verify(
      () => storage.write(
        key: TokenStore.sessionKey,
        value: any(named: 'value'),
        aOptions: null,
        iOptions: null,
        mOptions: null,
      ),
    ).called(1);
  });

  test('clear drops only the session key', () async {
    await store.clear();
    verify(() => storage.delete(key: TokenStore.sessionKey)).called(1);
  });

  test('readRaw is the plain read used for the settings blob', () async {
    when(() => storage.read(key: 'neml.settings')).thenAnswer((_) async => '{}');
    expect(await store.readRaw('neml.settings'), '{}');
  });
}
