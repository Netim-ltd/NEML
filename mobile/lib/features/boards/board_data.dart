// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api.dart';

/// The board jobs of the lab, newest first. A job is the raw JSON of the
/// learning lab (`boards` of `{op: state}`); the screens read what they show.
final boardsProvider = FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final state = await ref.watch(apiProvider).learningOp({'op': 'state'});
  final boards = state['boards'];
  final jobs = boards is List
      ? [for (final b in boards) asMap(b)]
      : <Map<String, dynamic>>[];
  return jobs.reversed.toList(growable: false);
});

Map<String, dynamic> asMap(Object? v) => v is Map
    ? v.map((k, val) => MapEntry(k.toString(), val))
    : <String, dynamic>{};

List<dynamic> asList(Object? v) => v is List ? v : const [];

String text(Object? v, [String fallback = '']) => v?.toString() ?? fallback;

double number(Object? v) => v is num ? v.toDouble() : double.tryParse('$v') ?? 0;

/// Pads, tracks and vias of a drawn board, read from the cross-check geometry.
class BoardGeometry {
  const BoardGeometry({
    required this.width,
    required this.height,
    required this.parts,
    required this.pads,
    required this.tracks,
    required this.vias,
  });

  final double width;
  final double height;
  final Map<String, ({double x, double y})> parts;
  final List<PadShape> pads;
  final List<TrackShape> tracks;
  final List<ViaShape> vias;

  /// Null when the job has no geometry (a board made before it was recorded).
  static BoardGeometry? fromResult(Map<String, dynamic> result) {
    final geo = asMap(asMap(result['crosscheck'])['geometry']);
    if (geo.isEmpty) return null;
    final size = asList(result['size_mm']);
    if (size.length < 2) return null;
    return BoardGeometry(
      width: number(size[0]),
      height: number(size[1]),
      parts: {
        for (final e in asMap(geo['parts']).entries)
          e.key: (
            x: number(asList(e.value).isNotEmpty ? asList(e.value)[0] : 0),
            y: number(asList(e.value).length > 1 ? asList(e.value)[1] : 0),
          ),
      },
      pads: [
        for (final p in asList(geo['pads']))
          if (asList(p).length >= 7)
            PadShape(
              x: number(asList(p)[0]),
              y: number(asList(p)[1]),
              w: number(asList(p)[2]),
              h: number(asList(p)[3]),
              net: text(asList(p)[4]),
              ref: text(asList(p)[5]),
              through: text(asList(p)[6]) == 'tht',
            ),
      ],
      tracks: [
        for (final t in asList(geo['tracks']))
          if (asList(t).length >= 7)
            TrackShape(
              net: text(asList(t)[0]),
              back: text(asList(t)[1]) == 'B.Cu',
              x1: number(asList(t)[2]),
              y1: number(asList(t)[3]),
              x2: number(asList(t)[4]),
              y2: number(asList(t)[5]),
              w: number(asList(t)[6]),
            ),
      ],
      vias: [
        for (final v in asList(geo['vias']))
          if (asList(v).length >= 4)
            ViaShape(
              net: text(asList(v)[0]),
              x: number(asList(v)[1]),
              y: number(asList(v)[2]),
              d: number(asList(v)[3]),
            ),
      ],
    );
  }

  List<String> get nets =>
      ({for (final p in pads) p.net}..remove('')).toList()..sort();
}

class PadShape {
  const PadShape({
    required this.x,
    required this.y,
    required this.w,
    required this.h,
    required this.net,
    required this.ref,
    required this.through,
  });

  final double x, y, w, h;
  final String net, ref;
  final bool through;
}

class TrackShape {
  const TrackShape({
    required this.net,
    required this.back,
    required this.x1,
    required this.y1,
    required this.x2,
    required this.y2,
    required this.w,
  });

  final String net;
  final bool back;
  final double x1, y1, x2, y2, w;
}

class ViaShape {
  const ViaShape({
    required this.net,
    required this.x,
    required this.y,
    required this.d,
  });

  final String net;
  final double x, y, d;
}
