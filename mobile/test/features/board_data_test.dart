// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_test/flutter_test.dart';
import 'package:neml_mobile/features/boards/board_data.dart';

void main() {
  test('the board geometry is read from the cross-check of a finished job', () {
    final board = BoardGeometry.fromResult({
      'size_mm': [30, 20],
      'crosscheck': {
        'geometry': {
          'parts': {
            'U1': [10, 5],
          },
          'pads': [
            [9.5, 5, 1, 1, 'VCC', 'U1.1', 'smd'],
            [10.5, 5, 1, 1, 'GND', 'U1.2', 'tht'],
          ],
          'tracks': [
            ['VCC', 'F.Cu', 1, 1, 5, 1, 0.5],
          ],
          'vias': [
            ['VCC', 5, 1, 0.8],
          ],
        },
      },
    });
    expect(board, isNotNull);
    expect(board!.width, 30);
    expect(board.pads.length, 2);
    expect(board.pads.last.through, isTrue);
    expect(board.tracks.single.back, isFalse);
    expect(board.nets, ['GND', 'VCC']);
  });

  test('a job without geometry gives no drawing', () {
    expect(BoardGeometry.fromResult({'size_mm': [30, 20]}), isNull);
  });
}
