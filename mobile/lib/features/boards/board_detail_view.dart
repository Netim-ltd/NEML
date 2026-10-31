// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../shared/widgets.dart';
import 'board_data.dart';
import 'board_painter.dart';

/// One board in detail: the board drawn from its data (pick a net to follow it),
/// parts with their pins, nets, bill of materials, the checks and the team talk.
class BoardDetailView extends ConsumerWidget {
  const BoardDetailView({super.key, required this.boardId});

  final String boardId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final boards = ref.watch(boardsProvider);
    return AsyncView<List<Map<String, dynamic>>>(
      boards,
      onRetry: () => ref.invalidate(boardsProvider),
      builder: (jobs) {
        final job = jobs.where((j) => text(j['id']) == boardId).firstOrNull;
        if (job == null) {
          return NemlScaffold(
            title: 'Kart',
            body: const Center(child: Text('Kart bulunamadı.')),
          );
        }
        return _Detail(job: job, onRefresh: () => ref.invalidate(boardsProvider));
      },
    );
  }
}

class _Detail extends StatelessWidget {
  const _Detail({required this.job, required this.onRefresh});

  final Map<String, dynamic> job;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final result = asMap(job['result']);
    return DefaultTabController(
      length: 6,
      child: NemlScaffold(
        title: 'Kart ${text(job['id'])}',
        actions: [
          IconButton(
            tooltip: 'Yenile',
            icon: const Icon(Icons.refresh),
            onPressed: onRefresh,
          ),
        ],
        bottom: const TabBar(
          isScrollable: true,
          tabs: [
            Tab(text: 'Kart'),
            Tab(text: 'Parçalar'),
            Tab(text: 'Ağlar'),
            Tab(text: 'Malzeme'),
            Tab(text: 'Doğrulama'),
            Tab(text: 'Konuşma'),
          ],
        ),
        body: TabBarView(
          children: [
            _BoardTab(job: job, result: result),
            _PartsTab(result: result),
            _NetsTab(result: result),
            _BomTab(result: result),
            _ChecksTab(job: job, result: result),
            _TalkTab(job: job),
          ],
        ),
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty(this.message);

  final String message;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(padding: const EdgeInsets.all(24), child: Text(message)),
  );
}

class _BoardTab extends StatefulWidget {
  const _BoardTab({required this.job, required this.result});

  final Map<String, dynamic> job;
  final Map<String, dynamic> result;

  @override
  State<_BoardTab> createState() => _BoardTabState();
}

class _BoardTabState extends State<_BoardTab> {
  BoardLayer _layer = BoardLayer.both;
  String? _net;
  bool _labels = true;

  @override
  Widget build(BuildContext context) {
    final board = BoardGeometry.fromResult(widget.result);
    if (board == null) {
      return _Empty(
        widget.result.isEmpty
            ? 'Kart henüz bitmedi (${text(widget.job['state'])}).'
            : 'Bu kartın ayrıntılı çizimi yok (eski sürüm). Web panelinde resim olarak görünür.',
      );
    }
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        SegmentedButton<BoardLayer>(
          segments: const [
            ButtonSegment(value: BoardLayer.both, label: Text('İkisi')),
            ButtonSegment(value: BoardLayer.front, label: Text('Üst')),
            ButtonSegment(value: BoardLayer.back, label: Text('Alt')),
          ],
          selected: {_layer},
          onSelectionChanged: (s) => setState(() => _layer = s.first),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 6,
          runSpacing: 4,
          children: [
            for (final n in board.nets)
              ChoiceChip(
                label: Text(n),
                selected: _net == n,
                onSelected: (on) => setState(() => _net = on ? n : null),
              ),
          ],
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('Parça adları'),
          value: _labels,
          onChanged: (v) => setState(() => _labels = v),
        ),
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: InteractiveViewer(
            maxScale: 8,
            child: AspectRatio(
              aspectRatio: board.width / board.height,
              child: CustomPaint(
                painter: BoardPainter(
                  board,
                  layer: _layer,
                  net: _net,
                  labels: _labels,
                ),
              ),
            ),
          ),
        ),
        const SizedBox(height: 8),
        Text(
          '${board.tracks.length} iz · ${board.vias.length} via · ${board.pads.length} ped · '
          '${board.width.toStringAsFixed(1)} × ${board.height.toStringAsFixed(1)} mm\n'
          'Kırmızı üst bakır, mavi alt bakır, sarı via. İki parmakla yakınlaştırın; '
          'bir ağ seçince o ağ öne çıkar.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ],
    );
  }
}

class _PartsTab extends StatelessWidget {
  const _PartsTab({required this.result});

  final Map<String, dynamic> result;

  @override
  Widget build(BuildContext context) {
    final parts = asList(asMap(result['circuit'])['parts']);
    if (parts.isEmpty) return const _Empty('Parça listesi yok.');
    return ListView(
      children: [
        for (final raw in parts)
          Builder(
            builder: (context) {
              final p = asMap(raw);
              return ExpansionTile(
                title: Text('${text(p['ref'])} · ${text(p['value'])}'),
                subtitle: Text(
                  '${text(p['kind'])} · ${text(p['package'])} · ${text(p['part_number'])} · ${text(p['supplier'])}',
                ),
                children: [
                  for (final pin in asList(p['pins']))
                    ListTile(
                      dense: true,
                      leading: CircleAvatar(
                        radius: 14,
                        child: Text(
                          text(asList(pin).isNotEmpty ? asList(pin)[0] : ''),
                          style: const TextStyle(fontSize: 11),
                        ),
                      ),
                      title: Text(
                        text(asList(pin).length > 1 ? asList(pin)[1] : ''),
                      ),
                      subtitle: Text(
                        text(asList(pin).length > 2 ? asList(pin)[2] : ''),
                      ),
                      trailing: Text(
                        text(asList(pin).length > 3 ? asList(pin)[3] : ''),
                        style: const TextStyle(fontWeight: FontWeight.bold),
                      ),
                    ),
                ],
              );
            },
          ),
      ],
    );
  }
}

class _NetsTab extends StatelessWidget {
  const _NetsTab({required this.result});

  final Map<String, dynamic> result;

  @override
  Widget build(BuildContext context) {
    final nets = <String, List<String>>{};
    for (final raw in asList(asMap(result['circuit'])['parts'])) {
      final p = asMap(raw);
      for (final pin in asList(p['pins'])) {
        final l = asList(pin);
        if (l.length < 4) continue;
        nets.putIfAbsent(text(l[3]), () => []).add('${text(p['ref'])}.${text(l[0])}');
      }
    }
    if (nets.isEmpty) return const _Empty('Ağ listesi yok.');
    final routing = asMap(result['routing']);
    final routed = asList(routing['routed']).map(text).toSet();
    final unrouted = asList(routing['unrouted']).map(text).toSet();
    String state(String n) => unrouted.contains(n)
        ? 'çizilemedi'
        : routed.contains(n)
        ? 'çizildi'
        : n == 'GND'
        ? 'alt katman dökümü'
        : 'tek pin';
    final names = nets.keys.toList()..sort();
    return ListView(
      children: [
        for (final n in names)
          ListTile(
            title: Text(n),
            subtitle: Text(nets[n]!.join(', ')),
            trailing: Text(state(n)),
          ),
      ],
    );
  }
}

class _BomTab extends StatelessWidget {
  const _BomTab({required this.result});

  final Map<String, dynamic> result;

  @override
  Widget build(BuildContext context) {
    final rows = asList(result['bom']);
    if (rows.isEmpty) return const _Empty('Malzeme listesi yok.');
    return ListView(
      children: [
        for (final raw in rows)
          Builder(
            builder: (context) {
              final r = asMap(raw);
              final tr = asMap(r['tr']);
              final price = number(tr['price_try']);
              return ListTile(
                isThreeLine: true,
                title: Text('${text(r['part_number'])} × ${text(r['qty'])}'),
                subtitle: Text(
                  '${text(r['ref'])} · ${text(r['supplier'])}\n'
                  '${text(tr['status'], '?')}${text(tr['note']).isEmpty ? '' : ' — ${text(tr['note'])}'}',
                ),
                trailing: Text(price > 0 ? '${price.toStringAsFixed(2)} TL' : '-'),
              );
            },
          ),
        Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            'Fiyatı doğrulanan kalemlerin toplamı ≈ ${number(result['tr_total_try']).toStringAsFixed(0)} TL. '
            'Fiyat yalnızca mağaza sayfasından alıntıyla kabul edilir.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
      ],
    );
  }
}

class _ChecksTab extends StatelessWidget {
  const _ChecksTab({required this.job, required this.result});

  final Map<String, dynamic> job;
  final Map<String, dynamic> result;

  @override
  Widget build(BuildContext context) {
    if (result.isEmpty) {
      return _Empty(
        job['error'] != null
            ? text(job['error'])
            : 'Kart henüz bitmedi (${text(job['state'])}).',
      );
    }
    final erc = asMap(result['erc']);
    final cross = asMap(result['crosscheck']);
    final routing = asMap(result['routing']);
    final review = asMap(result['review']);
    final rounds = asList(result['rounds']);
    final crossText = cross['passed'] == true
        ? 'KiCad ile uyuşuyor'
        : cross['passed'] == false
        ? 'farklı düşünüyor'
        : 'çalışmadı';
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        _Fact('ERC (şema)', erc['passed'] == true ? 'geçti' : text(erc['detail'], 'hata var'), ok: erc['passed'] == true),
        _Fact('Yollar', result['clean'] == true ? 'KiCad DRC temiz' : 'DRC tam temiz değil', ok: result['clean'] == true),
        _Fact(
          'Yönlendirme',
          '${asList(routing['routed']).length} ağ çizildi · ${text(routing['tracks'])} iz · '
              '${text(routing['vias'])} via · ${text(routing['length_mm'])} mm bakır'
              '${asList(routing['unrouted']).isEmpty ? '' : ' · çizilemeyen: ${asList(routing['unrouted']).map(text).join(', ')}'}',
          ok: asList(routing['unrouted']).isEmpty,
        ),
        _Fact('İkinci okuyucu', crossText, ok: cross['passed'] == true),
        for (final i in asList(cross['issues']))
          Padding(
            padding: const EdgeInsets.only(left: 12, bottom: 4),
            child: Text(text(i), style: Theme.of(context).textTheme.bodySmall),
          ),
        if (rounds.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text('Yönlendirme turları', style: Theme.of(context).textTheme.titleSmall),
          for (final raw in rounds)
            Builder(
              builder: (context) {
                final rd = asMap(raw);
                final problems = asList(rd['problems']).map(text).toList();
                return ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: CircleAvatar(radius: 14, child: Text(text(rd['round']))),
                  title: Text('${text(rd['routed'])} ağ çizildi'),
                  subtitle: Text(problems.isEmpty ? 'temiz' : problems.join('; ')),
                );
              },
            ),
        ],
        const SizedBox(height: 12),
        Text('Eleştirmen', style: Theme.of(context).textTheme.titleSmall),
        Text(text(review['verdict']), style: const TextStyle(fontWeight: FontWeight.bold)),
        for (final r in asList(review['risks'])) Text('• ${text(r)}'),
        if (text(review['verify_first']).isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              'Önce doğrula: ${text(review['verify_first'])}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
        const SizedBox(height: 12),
        Text(
          'Sipariş vermek ya da üretmek için önce insan incelemesi şarttır (SPEC 13.2).',
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ],
    );
  }
}

class _Fact extends StatelessWidget {
  const _Fact(this.label, this.value, {required this.ok});

  final String label;
  final String value;
  final bool ok;

  @override
  Widget build(BuildContext context) => ListTile(
    dense: true,
    contentPadding: EdgeInsets.zero,
    leading: Icon(
      ok ? Icons.check_circle_outline : Icons.warning_amber_outlined,
      color: ok ? Colors.green : Colors.orange,
    ),
    title: Text(label),
    subtitle: Text(value),
  );
}

class _TalkTab extends StatelessWidget {
  const _TalkTab({required this.job});

  final Map<String, dynamic> job;

  @override
  Widget build(BuildContext context) {
    final talk = asList(job['talk']);
    if (talk.isEmpty) return const _Empty('Konuşma yok.');
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        for (final raw in talk)
          Builder(
            builder: (context) {
              final m = asMap(raw);
              return Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text.rich(
                  TextSpan(
                    children: [
                      TextSpan(
                        text: '${text(m['agent'])}: ',
                        style: const TextStyle(fontWeight: FontWeight.bold),
                      ),
                      TextSpan(text: text(m['text'])),
                    ],
                  ),
                ),
              );
            },
          ),
      ],
    );
  }
}
