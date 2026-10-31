// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neml_mobile/core/auth/auth.dart';
import 'package:neml_mobile/core/models.dart';
import 'package:neml_mobile/features/approvals/approvals_provider.dart';
import 'package:neml_mobile/features/approvals/approvals_view.dart';

import '../helpers.dart';

const _owner = Session(
  access: 'a',
  refresh: 'r',
  email: 'owner@neml',
  role: 'owner',
);
const _operator = Session(
  access: 'a',
  refresh: 'r',
  email: 'op@neml',
  role: 'operator',
);

Future<void> _pumpPanel(
  WidgetTester tester, {
  required int level,
  required Session session,
  required void Function() onApprove,
}) => tester.pumpWidget(
  wrap(
    ApprovalDecisionPanel(
      level: level,
      onApprove: (_) async => onApprove(),
      onReject: (_) async {},
    ),
    overrides: [sessionProvider.overrideWithValue(session)],
  ),
);

ButtonStyleButton _approveButton(WidgetTester tester) =>
    tester.widget<ButtonStyleButton>(find.byKey(const Key('approval-approve')));

void main() {
  group('level 4 approval (section 10.2 screen 10)', () {
    testWidgets('stays disabled until ONAYLIYORUM is typed', (tester) async {
      var approved = 0;
      await _pumpPanel(
        tester,
        level: 4,
        session: _owner,
        onApprove: () => approved++,
      );

      expect(_approveButton(tester).onPressed, isNull);

      await tester.enterText(find.byKey(const Key('level4-confirm')), 'onayla');
      await tester.pump();
      expect(_approveButton(tester).onPressed, isNull);

      await tester.enterText(
        find.byKey(const Key('level4-confirm')),
        kLevel4ConfirmWord,
      );
      await tester.pump();
      expect(_approveButton(tester).onPressed, isNotNull);

      await tester.tap(find.byKey(const Key('approval-approve')));
      await tester.pumpAndSettle();
      expect(approved, 1);
    });

    testWidgets('an operator can never approve level 4', (tester) async {
      await _pumpPanel(
        tester,
        level: 4,
        session: _operator,
        onApprove: () {},
      );
      await tester.enterText(
        find.byKey(const Key('level4-confirm')),
        kLevel4ConfirmWord,
      );
      await tester.pump();
      expect(_approveButton(tester).onPressed, isNull);
      expect(find.text('Seviye 4 onayını yalnızca owner verebilir.'), findsOne);
    });

    testWidgets('levels 1-3 need no typed confirmation', (tester) async {
      var approved = 0;
      await _pumpPanel(
        tester,
        level: 3,
        session: _operator,
        onApprove: () => approved++,
      );
      expect(find.byKey(const Key('level4-confirm')), findsNothing);
      expect(_approveButton(tester).onPressed, isNotNull);
      await tester.tap(find.byKey(const Key('approval-approve')));
      await tester.pumpAndSettle();
      expect(approved, 1);
    });
  });

  group('role gate (section 5.5)', () {
    test('viewers cannot decide at all', () {
      const viewer = Session(
        access: 'a',
        refresh: 'r',
        email: 'v@neml',
        role: 'viewer',
      );
      expect(approvalBlockReason(viewer, 1), ApprovalBlock.notAuthorized);
      expect(approvalBlockReason(null, 1), ApprovalBlock.notAuthorized);
    });

    test('operators decide 1-3, only the owner decides 4', () {
      expect(approvalBlockReason(_operator, 3), isNull);
      expect(approvalBlockReason(_operator, 4), ApprovalBlock.ownerOnly);
      expect(approvalBlockReason(_owner, 4), isNull);
    });

    test('the typed word must match exactly', () {
      // Exactly, meaning character for character. Surrounding whitespace is NOT
      // trimmed: section 10.2 screen 10 says the operator types "ONAYLIYORUM",
      // and a level 4 gate (print, PCB order, firmware flash) does not round in
      // the operator's favour. approvals_test.dart pins the full rejection set.
      expect(level4ConfirmationOk(4, 'ONAYLIYORUM'), isTrue);
      expect(level4ConfirmationOk(4, ' ONAYLIYORUM '), isFalse);
      expect(level4ConfirmationOk(4, 'onaylıyorum'), isFalse);
      expect(level4ConfirmationOk(3, ''), isTrue);
    });
  });
}
