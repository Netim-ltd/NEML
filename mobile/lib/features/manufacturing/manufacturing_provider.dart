// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../core/network/api.dart';
import '../../core/realtime/live_client.dart';

class ManufacturingState {
  const ManufacturingState({this.printer, this.jobs = const []});

  final PrinterStatus? printer;
  final List<PrintJob> jobs;

  ManufacturingState copyWith({PrinterStatus? printer, List<PrintJob>? jobs}) =>
      ManufacturingState(
        printer: printer ?? this.printer,
        jobs: jobs ?? this.jobs,
      );
}

/// Section 10.2 screen 11 — printer status, queue, cancel, QC form.
class ManufacturingNotifier extends AsyncNotifier<ManufacturingState> {
  @override
  Future<ManufacturingState> build() async {
    ref.listen(liveEventsProvider, (_, next) {
      final event = next.value;
      if (event?.name == 'PrintProgress') _applyProgress(event!.data);
    });

    final api = ref.read(apiProvider);
    final jobs = await api.printJobs();
    // Section 9.3 exposes no printer list, so the printer is taken from the
    // queue itself.
    final printerId = jobs.isEmpty ? null : jobs.first.printerId;
    return ManufacturingState(
      jobs: jobs,
      printer: printerId == null ? null : await api.printerStatus(printerId),
    );
  }

  void _applyProgress(Map<String, dynamic> data) {
    final current = state.value;
    final printer = current?.printer;
    if (current == null || printer == null) return;
    state = AsyncValue.data(
      current.copyWith(printer: printer.mergeProgress(data)),
    );
  }

  Future<void> cancel(String jobId) async {
    await ref.read(apiProvider).cancelPrint(jobId);
    ref.invalidateSelf();
  }

  Future<void> submitQc(String jobId, Map<String, dynamic> qc) async {
    await ref.read(apiProvider).submitQc(jobId, qc);
    ref.invalidateSelf();
  }
}

final manufacturingProvider =
    AsyncNotifierProvider<ManufacturingNotifier, ManufacturingState>(
      ManufacturingNotifier.new,
    );

/// Quality-control checks of section 12.5, with the thresholds shown to the
/// operator next to the field they apply to.
const kQcTolerance = <String, String>{
  'dim_1_mm': '+/- 0.3 mm',
  'dim_2_mm': '+/- 0.3 mm',
  'dim_3_mm': '+/- 0.3 mm',
  'mass_g': '+/- 5% (CAD)',
  'warp_mm': '<= 0.5 mm',
};

/// The same thresholds as numbers, for the live check (section 12.5).
const kQcDimToleranceMm = 0.3;
const kQcMassToleranceRatio = 0.05;
const kQcWarpLimitMm = 0.5;

/// Parses a caliper reading. The Turkish keyboard puts a comma on the decimal
/// key, so `20,15` has to mean what the operator meant by it.
double? qcNumber(String text) =>
    double.tryParse(text.trim().replaceAll(',', '.'));

/// Section 12.5 in one line, evaluated on every keystroke.
///
/// `null` means "no verdict yet": the field is empty, unparseable, or the
/// nominal it would be compared against is not known. An unknown nominal is
/// never reported as a failure — that would put a good part in the bin.
/// A nanometre of slack, so that binary floating point cannot report a part
/// that is exactly on the tolerance as scrap: 19.7 against a 20.0 nominal is
/// 0.30000000000000071 away in doubles, and 0.3 is a PASS on a caliper.
const _qcEpsilon = 1e-9;

bool? qcPass(double? measured, double? nominal, double? tolerance) =>
    measured == null || nominal == null || tolerance == null
    ? null
    : (measured - nominal).abs() <= tolerance + _qcEpsilon;
