// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/auth/auth.dart';
import '../../core/network/api.dart';
import '../../shared/widgets.dart';

/// Every robot model (plus the lab-wide set) and how many required fields are
/// still empty. The lab answers; nothing is cached here.
final modelSettingsListProvider = FutureProvider.autoDispose<List<ModelRow>>((
  ref,
) async {
  final result = await ref.watch(apiProvider).modelSettingsList();
  final models = result['models'];
  return [
    if (models is List)
      for (final m in models)
        if (m is Map)
          ModelRow(
            '${m['modelId']}',
            m['missingRequired'] is List
                ? (m['missingRequired'] as List<Object?>).length
                : 0,
          ),
  ];
});

final modelSettingsProvider = FutureProvider.autoDispose
    .family<Map<String, dynamic>, String>(
      (ref, modelId) => ref.watch(apiProvider).modelSettings(modelId),
    );

class ModelRow {
  const ModelRow(this.id, this.missing);
  final String id;
  final int missing;
}

bool _tr(BuildContext context) =>
    Localizations.localeOf(context).languageCode == 'tr';

String _modelTitle(BuildContext context, String id) =>
    id == '_lab' ? (_tr(context) ? 'Laboratuvar (genel)' : 'Lab (global)') : id;

/// Admin screen: pick a model.
class ModelSettingsListView extends ConsumerWidget {
  const ModelSettingsListView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tr = _tr(context);
    return NemlScaffold(
      title: tr ? 'Robot modeli ayarları' : 'Robot model settings',
      body: AsyncView<List<ModelRow>>(
        ref.watch(modelSettingsListProvider),
        onRetry: () => ref.invalidate(modelSettingsListProvider),
        builder: (rows) => ListView(
          children: [
            for (final row in rows)
              ListTile(
                key: Key('model-${row.id}'),
                leading: Icon(
                  row.missing == 0
                      ? Icons.check_circle_outline
                      : Icons.error_outline,
                  color: row.missing == 0
                      ? Colors.green
                      : Theme.of(context).colorScheme.error,
                ),
                title: Text(_modelTitle(context, row.id)),
                subtitle: Text(
                  row.missing == 0
                      ? (tr ? 'Zorunlu alanlar tamam' : 'Required fields set')
                      : (tr
                            ? '${row.missing} zorunlu alan eksik'
                            : '${row.missing} required fields missing'),
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => context.push('/settings/models/${row.id}'),
              ),
          ],
        ),
      ),
    );
  }
}

/// Admin screen: the fields of one model. Required ones are marked; a
/// recommended field shows the default that applies until it is set. Only the
/// owner may save (section 5.5); everyone else reads.
class ModelSettingsDetailView extends ConsumerStatefulWidget {
  const ModelSettingsDetailView({super.key, required this.modelId});

  final String modelId;

  @override
  ConsumerState<ModelSettingsDetailView> createState() =>
      _ModelSettingsDetailState();
}

class _ModelSettingsDetailState extends ConsumerState<ModelSettingsDetailView> {
  final Map<String, TextEditingController> _controllers = {};
  Map<String, dynamic>? _loaded;
  bool _saving = false;

  @override
  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  List<Map<String, dynamic>> _fields(Map<String, dynamic> view) {
    final raw = view['fields'];
    return [
      if (raw is List)
        for (final f in raw)
          if (f is Map) f.map((k, v) => MapEntry('$k', v)),
    ];
  }

  void _adopt(Map<String, dynamic> view) {
    if (identical(_loaded, view)) return;
    _loaded = view;
    for (final f in _fields(view)) {
      final key = '${f['key']}';
      final value = f['value'];
      _controllers
          .putIfAbsent(key, TextEditingController.new)
          .text = value == null ? '' : '$value';
    }
  }

  Future<void> _save(Map<String, dynamic> view) async {
    final tr = _tr(context);
    final values = <String, double?>{};
    for (final f in _fields(view)) {
      final key = '${f['key']}';
      final text = (_controllers[key]?.text ?? '').trim().replaceAll(',', '.');
      final before = f['value'];
      if (text.isEmpty) {
        if (before != null) values[key] = null; // clearing a field
        continue;
      }
      final parsed = double.tryParse(text);
      if (parsed == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(tr ? 'Geçersiz sayı: $key' : 'Invalid number: $key')),
        );
        return;
      }
      if (before is! num || before.toDouble() != parsed) {
        values[key] = parsed;
      }
    }
    if (values.isEmpty) return;
    setState(() => _saving = true);
    try {
      await ref.read(apiProvider).saveModelSettings(widget.modelId, values);
      ref.invalidate(modelSettingsProvider(widget.modelId));
      ref.invalidate(modelSettingsListProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(tr ? 'Kaydedildi' : 'Saved')),
        );
      }
    } on Object catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('$e')),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final tr = _tr(context);
    final isOwner = ref.watch(sessionProvider)?.role == 'owner';
    final async = ref.watch(modelSettingsProvider(widget.modelId));
    return NemlScaffold(
      title: _modelTitle(context, widget.modelId),
      body: AsyncView<Map<String, dynamic>>(
        async,
        onRetry: () => ref.invalidate(modelSettingsProvider(widget.modelId)),
        builder: (view) {
          _adopt(view);
          final fields = _fields(view);
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (!isOwner)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Text(
                    tr
                        ? 'Değerleri yalnızca sahip değiştirebilir.'
                        : 'Only the owner can change these values.',
                  ),
                ),
              for (final f in fields) _field(context, f, isOwner),
              const SizedBox(height: 16),
              if (isOwner)
                FilledButton(
                  key: const Key('save-model-settings'),
                  onPressed: _saving ? null : () => _save(view),
                  child: Text(tr ? 'Kaydet' : 'Save'),
                ),
            ],
          );
        },
      ),
    );
  }

  Widget _field(BuildContext context, Map<String, dynamic> f, bool editable) {
    final tr = _tr(context);
    final key = '${f['key']}';
    final required = f['level'] == 'required';
    final unit = '${f['unit']}';
    final label = '${tr ? f['label_tr'] : f['label_en']}';
    final fallback = f['default'];
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  label,
                  style: Theme.of(context).textTheme.titleSmall,
                ),
              ),
              Chip(
                label: Text(
                  required
                      ? (tr ? 'zorunlu' : 'required')
                      : (tr ? 'önerilen' : 'recommended'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          TextField(
            key: Key('field-$key'),
            controller: _controllers[key],
            enabled: editable,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(
              suffixText: unit,
              hintText: fallback == null
                  ? null
                  : (tr ? 'varsayılan: $fallback' : 'default: $fallback'),
              helperText: '${f['help_tr']}',
              helperMaxLines: 4,
              errorText: (required && f['value'] == null)
                  ? (tr ? 'Bu değer girilmeden karar verilmez' : 'Not decided until set')
                  : null,
            ),
          ),
        ],
      ),
    );
  }
}
