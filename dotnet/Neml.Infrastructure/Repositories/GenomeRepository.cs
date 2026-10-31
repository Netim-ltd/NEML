// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.EntityFrameworkCore;
using Neml.Domain.Dtos;
using Neml.Domain.Enums;
using Neml.Infrastructure.Persistence;

namespace Neml.Infrastructure.Repositories;

/// <summary>GET /genomes/tree of section 9.3 — the lineage the mobile app draws.</summary>
public class GenomeRepository(NemlDbContext db)
{
    private record Row(string Id, string Name, int Version, GenomeStatus Status, string? ParentId, decimal? FitnessScore);

    /// <summary>
    /// ponytail: reads the whole genomes table and assembles the tree in memory. That is a few
    /// hundred rows per campaign; swap in a recursive CTE if lineage ever reaches five figures.
    /// </summary>
    public async Task<IReadOnlyList<GenomeNodeResponse>> TreeAsync(CancellationToken ct = default)
    {
        var rows = await db.Genomes.AsNoTracking()
            .OrderBy(g => g.CreatedAt)
            .Select(g => new Row(g.Id, g.Name, g.Version, g.Status, g.ParentId, g.FitnessScore))
            .ToListAsync(ct);

        var known = rows.Select(r => r.Id).ToHashSet();
        var childrenOf = rows.Where(r => r.ParentId is not null).ToLookup(r => r.ParentId!);
        var seen = new HashSet<string>();

        GenomeNodeResponse Build(Row row)
        {
            // A self reference loop cannot be created through the FK alone, but an UPDATE could;
            // seen keeps a corrupted row from recursing forever.
            List<GenomeNodeResponse> children = seen.Add(row.Id)
                ? childrenOf[row.Id].Select(Build).ToList()
                : [];
            return new GenomeNodeResponse(row.Id, row.Name, row.Version, row.Status, row.ParentId,
                row.FitnessScore, children);
        }

        return rows.Where(r => r.ParentId is null || !known.Contains(r.ParentId)).Select(Build).ToList();
    }
}
