// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../shared/widgets.dart';
import 'skills_provider.dart';

/// Section 10.2 screen 9 — sim/real success rates with their 95% intervals,
/// version history and preconditions.
class SkillsView extends ConsumerWidget {
  const SkillsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final skills = ref.watch(skillsProvider);

    return NemlScaffold(
      title: l10n.skills,
      body: AsyncView<List<Skill>>(
        skills,
        onRetry: () => ref.invalidate(skillsProvider),
        builder: (items) => items.isEmpty
            ? Center(child: Text(l10n.empty))
            : ListView(
                children: [
                  for (final skill in items)
                    Card(
                      child: ExpansionTile(
                        title: Text('${skill.skillKey} v${skill.version}'),
                        trailing: StatusChip(skill.status),
                        children: [
                          RateBar(
                            label: l10n.sim,
                            validation: skill.forEnv('sim'),
                          ),
                          RateBar(
                            label: l10n.real,
                            validation: skill.forEnv('real'),
                          ),
                          if (skill.preconditions.isNotEmpty)
                            ListTile(
                              title: Text(l10n.preconditions),
                              subtitle: Text('${skill.preconditions}'),
                            ),
                          _Versions(skillKey: skill.skillKey),
                        ],
                      ),
                    ),
                ],
              ),
      ),
    );
  }
}

/// Success-rate bar with the 95% confidence interval drawn as a lighter band
/// behind the point estimate (section 7 `skill_validations`).
class RateBar extends StatelessWidget {
  const RateBar({super.key, required this.label, required this.validation});

  final String label;
  final SkillValidation? validation;

  @override
  Widget build(BuildContext context) {
    final l10n = tr(context);
    final scheme = Theme.of(context).colorScheme;
    final v = validation;
    if (v == null) {
      return ListTile(title: Text(label), subtitle: Text(l10n.none));
    }
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('$label - ${l10n.successRate}'),
              Text(
                '${(v.rate * 100).toStringAsFixed(1)}%  '
                '(${v.successes}/${v.trials} ${l10n.trials})',
                style: Theme.of(context).textTheme.labelSmall,
              ),
            ],
          ),
          const SizedBox(height: 4),
          LayoutBuilder(
            builder: (context, constraints) => SizedBox(
              height: 14,
              child: Stack(
                children: [
                  Positioned(
                    left: constraints.maxWidth * v.ci95Low,
                    width:
                        constraints.maxWidth * (v.ci95High - v.ci95Low).abs(),
                    top: 3,
                    bottom: 3,
                    child: ColoredBox(
                      color: scheme.primary.withValues(alpha: 0.25),
                    ),
                  ),
                  Positioned(
                    left: constraints.maxWidth * v.rate - 1,
                    width: 3,
                    top: 0,
                    bottom: 0,
                    child: ColoredBox(color: scheme.primary),
                  ),
                ],
              ),
            ),
          ),
          Text(
            '${l10n.confidenceInterval}: '
            '${v.ci95Low.toStringAsFixed(3)} - ${v.ci95High.toStringAsFixed(3)}',
            style: Theme.of(context).textTheme.labelSmall,
          ),
          if (v.failureModes.isNotEmpty)
            Text(
              '${l10n.failureModes}: ${v.failureModes.join(', ')}',
              style: Theme.of(context).textTheme.labelSmall,
            ),
        ],
      ),
    );
  }
}

class _Versions extends ConsumerWidget {
  const _Versions({required this.skillKey});

  final String skillKey;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = tr(context);
    final versions = ref.watch(skillVersionsProvider(skillKey));
    return AsyncView<List<Skill>>(
      versions,
      onRetry: () => ref.invalidate(skillVersionsProvider(skillKey)),
      builder: (items) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Text(
              l10n.versionHistory,
              style: Theme.of(context).textTheme.titleSmall,
            ),
          ),
          for (final v in items)
            ListTile(
              title: Text('v${v.version}'),
              trailing: StatusChip(v.status),
            ),
        ],
      ),
    );
  }
}
