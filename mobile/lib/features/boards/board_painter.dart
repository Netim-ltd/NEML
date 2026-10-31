// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';

import 'board_data.dart';

enum BoardLayer { both, front, back }

/// Draws a board from its own data: outline, copper of both layers, vias, pads
/// and the part names. A picked [net] stays bright, everything else dims.
class BoardPainter extends CustomPainter {
  BoardPainter(
    this.board, {
    this.layer = BoardLayer.both,
    this.net,
    this.labels = true,
  });

  final BoardGeometry board;
  final BoardLayer layer;
  final String? net;
  final bool labels;

  static const _front = Color(0xFFE5534B);
  static const _back = Color(0xFF4A8FE7);
  static const _gold = Color(0xFFC9B458);
  static const _pad = Color(0xFFE0A05A);
  static const _hole = Color(0xFFD8C46A);

  double _alpha(String n) => net == null || net == n ? 1 : 0.18;

  @override
  void paint(Canvas canvas, Size size) {
    final k = size.width / board.width;
    Offset at(double x, double y) => Offset(x * k, y * k);

    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(0, 0, board.width * k, board.height * k),
        Radius.circular(0.6 * k),
      ),
      Paint()..color = const Color(0xFF0D3B2E),
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(0, 0, board.width * k, board.height * k),
        Radius.circular(0.6 * k),
      ),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 0.3 * k
        ..color = const Color(0xFFE2B341),
    );

    for (final t in board.tracks) {
      if (layer != BoardLayer.both && (layer == BoardLayer.back) != t.back) {
        continue;
      }
      canvas.drawLine(
        at(t.x1, t.y1),
        at(t.x2, t.y2),
        Paint()
          ..strokeCap = StrokeCap.round
          ..strokeWidth = t.w * k
          ..color = (t.back ? _back : _front).withValues(alpha: _alpha(t.net)),
      );
    }

    for (final v in board.vias) {
      final a = _alpha(v.net);
      canvas.drawCircle(
        at(v.x, v.y),
        v.d / 2 * k,
        Paint()..color = _gold.withValues(alpha: a),
      );
      canvas.drawCircle(
        at(v.x, v.y),
        v.d / 4 * k,
        Paint()..color = const Color(0xFF0D3B2E).withValues(alpha: a),
      );
    }

    for (final p in board.pads) {
      if (layer == BoardLayer.back && !p.through) continue;
      final r = Rect.fromCenter(
        center: at(p.x, p.y),
        width: p.w * k,
        height: p.h * k,
      );
      final radius = p.through ? (p.w < p.h ? p.w : p.h) / 2 * k : 0.08 * k;
      canvas.drawRRect(
        RRect.fromRectAndRadius(r, Radius.circular(radius)),
        Paint()
          ..color = (p.through ? _hole : _pad).withValues(alpha: _alpha(p.net)),
      );
    }

    if (labels) {
      for (final e in board.parts.entries) {
        final tp = TextPainter(
          text: TextSpan(
            text: e.key,
            style: TextStyle(
              color: Colors.white,
              fontSize: (1.1 * k).clamp(6, 40).toDouble(),
              shadows: const [Shadow(blurRadius: 2)],
            ),
          ),
          textDirection: TextDirection.ltr,
        )..layout();
        tp.paint(
          canvas,
          at(e.value.x, e.value.y - 1.4) - Offset(tp.width / 2, tp.height / 2),
        );
      }
    }
  }

  @override
  bool shouldRepaint(BoardPainter old) =>
      old.board != board ||
      old.layer != layer ||
      old.net != net ||
      old.labels != labels;
}
