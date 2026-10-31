// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../shared/widgets.dart';
import 'manufacturing_provider.dart';

class ManufacturingView extends ConsumerWidget {
  const ManufacturingView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final state = ref.watch(manufacturingProvider);

    return NemlScaffold(
      title: l10n.manufacturing,
      body: AsyncView<ManufacturingState>(
        state,
        onRetry: () => ref.invalidate(manufacturingProvider),
        builder: (data) => ListView(
          children: [
            if (data.printer != null) _PrinterCard(data.printer!),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
              child: Text(
                l10n.printQueue,
                style: Theme.of(context).textTheme.titleSmall,
              ),
            ),
            if (data.jobs.isEmpty) ListTile(title: Text(l10n.empty)),
            for (final job in data.jobs)
              Card(
                child: ListTile(
                  title: Text(job.name.isEmpty ? job.id : job.name),
                  subtitle: Text(
                    '${job.printerId} - '
                    '${job.estTimeH?.toStringAsFixed(1) ?? '-'} h / '
                    '${job.estFilamentG?.toStringAsFixed(0) ?? '-'} g / '
                    '${job.estCostTry?.toStringAsFixed(2) ?? '-'} TRY',
                  ),
                  leading: StatusChip(job.state),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (job.state == 'done')
                        IconButton(
                          key: Key('qc-${job.id}'),
                          icon: const Icon(Icons.rule),
                          tooltip: l10n.qualityControl,
                          onPressed: () => _qcSheet(context, job),
                        ),
                      if (job.state == 'queued' || job.state == 'printing')
                        IconButton(
                          icon: const Icon(Icons.cancel_outlined),
                          tooltip: l10n.cancelPrint,
                          onPressed: () async {
                            try {
                              await ref
                                  .read(manufacturingProvider.notifier)
                                  .cancel(job.id);
                            } on Object catch (e) {
                              if (context.mounted) {
                                reportWriteResult(context, unwrapError(e));
                              }
                            }
                          },
                        ),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }
}

/// Live printer status, fed by the section 9.4 `PrintProgress` event.
class _PrinterCard extends StatelessWidget {
  const _PrinterCard(this.printer);

  final PrinterStatus printer;

  @override
  Widget build(BuildContext context) {
    final l10n = tr(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '${l10n.printerStatus} - ${printer.id}',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                StatusChip(printer.state),
              ],
            ),
            Row(
              children: [
                Expanded(
                  child: MetricTile(
                    l10n.nozzle,
                    '${printer.nozzleC.toStringAsFixed(0)} / '
                    '${printer.targetNozzleC.toStringAsFixed(0)} C',
                  ),
                ),
                Expanded(
                  child: MetricTile(
                    l10n.bed,
                    '${printer.bedC.toStringAsFixed(0)} / '
                    '${printer.targetBedC.toStringAsFixed(0)} C',
                  ),
                ),
              ],
            ),
            Row(
              children: [
                Expanded(child: MetricTile(l10n.layer, '${printer.layer}')),
                Expanded(child: MetricTile(l10n.eta, '${printer.etaMin} min')),
                Expanded(
                  child: MetricTile(
                    l10n.progress,
                    '${printer.pct.toStringAsFixed(0)}%',
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            LinearProgressIndicator(
              key: const Key('print-progress'),
              value: (printer.pct / 100).clamp(0, 1),
            ),
          ],
        ),
      ),
    );
  }
}

Future<void> _qcSheet(BuildContext context, PrintJob job) =>
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => Padding(
        padding: EdgeInsets.only(
          left: 16,
          right: 16,
          top: 16,
          bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 16,
        ),
        child: _QcForm(job),
      ),
    );

/// Section 12.5 quality-control form: caliper measurements, pin gauge, scale,
/// layer adhesion and warp.
///
/// Every numeric field is checked against its threshold on each keystroke. The
/// operator is standing at the printer with a caliper in one hand; finding out
/// a part is out of tolerance must not require submitting the form.
///
/// The CAD nominal each dimension is compared against is typed in next to it:
/// only the operator knows which three points were measured, and section 12.5's
/// systematic-deviation rule ("3 ardisik parcada ayni yon") needs the sign of
/// the deviation, not just its magnitude. The mass nominal is the slicer
/// estimate that came with the job (section 6.4 `estimate`).
class _QcForm extends ConsumerStatefulWidget {
  const _QcForm(this.job);

  final PrintJob job;

  @override
  ConsumerState<_QcForm> createState() => _QcFormState();
}

class _QcFormState extends ConsumerState<_QcForm> {
  final _nominal = List.generate(3, (_) => TextEditingController());
  final _dim = List.generate(3, (_) => TextEditingController());
  final _mass = TextEditingController();
  final _warp = TextEditingController();
  var _holeOk = true;
  var _adhesionOk = true;
  var _busy = false;

  @override
  void dispose() {
    for (final c in [..._nominal, ..._dim, _mass, _warp]) {
      c.dispose();
    }
    super.dispose();
  }

  double? get _massNominal => widget.job.estFilamentG;

  bool? _dimVerdict(int i) => qcPass(
    qcNumber(_dim[i].text),
    qcNumber(_nominal[i].text),
    kQcDimToleranceMm,
  );

  bool? get _massVerdict => qcPass(
    qcNumber(_mass.text),
    _massNominal,
    _massNominal == null ? null : _massNominal! * kQcMassToleranceRatio,
  );

  /// Warp is measured against a flat surface, so its nominal is zero.
  bool? get _warpVerdict => qcPass(qcNumber(_warp.text), 0, kQcWarpLimitMm);

  List<bool?> get _verdicts => [
    _dimVerdict(0),
    _dimVerdict(1),
    _dimVerdict(2),
    _massVerdict,
    _warpVerdict,
  ];

  /// Every measurement is present. A verdict may still be `null` (an unknown
  /// nominal), which must not block recording what was measured.
  bool get _complete =>
      [..._dim, _mass, _warp].every((c) => qcNumber(c.text) != null);

  bool get _partOk =>
      _holeOk && _adhesionOk && !_verdicts.contains(false) && _complete;

  Widget _number(
    String id,
    TextEditingController controller,
    String label, {
    String? helper,
    bool? verdict,
  }) {
    final scheme = Theme.of(context).colorScheme;
    final l10n = tr(context);
    return TextField(
      key: Key('qc-$id'),
      controller: controller,
      keyboardType: const TextInputType.numberWithOptions(
        decimal: true,
        signed: true,
      ),
      onChanged: (_) => setState(() {}),
      decoration: InputDecoration(
        labelText: label,
        helperText: helper,
        suffix: verdict == null
            ? null
            : Text(
                verdict ? l10n.pass : l10n.fail,
                key: Key('qc-$id-verdict'),
                style: TextStyle(
                  color: verdict ? scheme.tertiary : scheme.error,
                  fontWeight: FontWeight.w600,
                ),
              ),
      ),
    );
  }

  Future<void> _submit() async {
    setState(() => _busy = true);
    try {
      await ref.read(manufacturingProvider.notifier).submitQc(widget.job.id, {
        for (var i = 0; i < 3; i++) 'dim_${i + 1}_mm': qcNumber(_dim[i].text),
        for (var i = 0; i < 3; i++)
          'dim_${i + 1}_nominal_mm': qcNumber(_nominal[i].text),
        'mass_g': qcNumber(_mass.text),
        'mass_nominal_g': _massNominal,
        'warp_mm': qcNumber(_warp.text),
        'hole_gauge_ok': _holeOk,
        'layer_adhesion_ok': _adhesionOk,
      });
      if (mounted) Navigator.of(context).pop();
    } on Object catch (e) {
      if (mounted) reportWriteResult(context, unwrapError(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = tr(context);
    final scheme = Theme.of(context).colorScheme;
    final job = widget.job;
    final massHelper = _massNominal == null
        ? kQcTolerance['mass_g']
        : '${kQcTolerance['mass_g']} = '
              '${_massNominal!.toStringAsFixed(1)} g';

    return SingleChildScrollView(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            '${l10n.qualityControl} - ${job.name.isEmpty ? job.id : job.name}',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          Text(l10n.qcDimensions, style: Theme.of(context).textTheme.labelSmall),
          for (var i = 0; i < 3; i++) ...[
            _number('dim-$i-cad', _nominal[i], '${i + 1}. CAD (mm)'),
            _number(
              'dim-$i',
              _dim[i],
              '${i + 1}. ${l10n.qcDimensions}',
              helper: kQcTolerance['dim_${i + 1}_mm'],
              verdict: _dimVerdict(i),
            ),
          ],
          _number(
            'mass',
            _mass,
            l10n.qcMass,
            helper: massHelper,
            verdict: _massVerdict,
          ),
          _number(
            'warp',
            _warp,
            l10n.qcWarp,
            helper: kQcTolerance['warp_mm'],
            verdict: _warpVerdict,
          ),
          SwitchListTile(
            key: const Key('qc-hole'),
            value: _holeOk,
            title: Text(l10n.qcHoleDiameter),
            subtitle: Text(_holeOk ? l10n.pass : l10n.fail),
            onChanged: (v) => setState(() => _holeOk = v),
          ),
          SwitchListTile(
            key: const Key('qc-adhesion'),
            value: _adhesionOk,
            title: Text(l10n.qcLayerAdhesion),
            subtitle: Text(_adhesionOk ? l10n.pass : l10n.fail),
            onChanged: (v) => setState(() => _adhesionOk = v),
          ),
          if (_complete)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(
                '${l10n.qualityControl}: ${_partOk ? l10n.pass : l10n.fail}',
                key: const Key('qc-verdict'),
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: _partOk ? scheme.tertiary : scheme.error,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          const SizedBox(height: 12),
          FilledButton(
            key: const Key('qc-submit'),
            onPressed: _complete && !_busy ? _submit : null,
            child: Text(l10n.submit),
          ),
        ],
      ),
    );
  }
}
