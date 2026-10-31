// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neml_mobile/shared/widgets.dart';

import '../helpers.dart';

void main() {
  const sliderKey = Key('confirm-slider');
  var fired = 0;

  setUp(() => fired = 0);

  Future<void> pumpSlider(WidgetTester tester) async {
    await tester.pumpWidget(
      wrap(
        ConfirmSlider(
          label: 'ACIL DURDURMA',
          confirmLabel: 'TEKRAR KAYDIR',
          onConfirmed: () => fired++,
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('e-stop needs two full slides (section 10.2 screen 3)', (
    tester,
  ) async {
    await pumpSlider(tester);
    expect(find.text('ACIL DURDURMA'), findsOne);

    await tester.drag(find.byKey(sliderKey), const Offset(800, 0));
    await tester.pumpAndSettle();
    expect(fired, 0, reason: 'one slide must not stop a robot');
    expect(find.text('TEKRAR KAYDIR'), findsOne);

    await tester.drag(find.byKey(sliderKey), const Offset(800, 0));
    await tester.pumpAndSettle();
    expect(fired, 1);
    expect(find.text('ACIL DURDURMA'), findsOne, reason: 'resets after firing');
  });

  testWidgets('a partial slide does not count as a pass', (tester) async {
    await pumpSlider(tester);
    final box = tester.getRect(find.byKey(sliderKey));

    for (var i = 0; i < 2; i++) {
      await tester.dragFrom(box.centerLeft + const Offset(4, 0), const Offset(20, 0));
      await tester.pumpAndSettle();
    }

    expect(fired, 0);
    expect(find.text('ACIL DURDURMA'), findsOne);
  });
}
