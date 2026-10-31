// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Data.Common;
using System.Text;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Neml.Domain.Dtos;
using Neml.Infrastructure.Persistence;

namespace Neml.Infrastructure.Repositories;

/// <summary>
/// telemetry is keyless and partitioned, so EF cannot track it: every read and write here is
/// plain ADO over the EF connection. Serves GET /robots/{id}/telemetry and the bridge batch.
/// </summary>
public class TelemetryRepository(NemlDbContext db)
{
    /// <summary>Allowed aggregations. Empty string means raw samples, no bucketing.</summary>
    private static readonly Dictionary<string, string> Aggregations = new(StringComparer.OrdinalIgnoreCase)
    {
        ["raw"] = "",
        ["avg"] = "avg(value)",
        ["min"] = "min(value)",
        ["max"] = "max(value)",
        ["sum"] = "sum(value)",
        ["count"] = "count(value)::double precision",
    };

    /// <summary>
    /// Aggregated queries bucket by minute, the same resolution the section 7 retention policy
    /// downsamples raw telemetry to after 90 days.
    /// </summary>
    public async Task<IReadOnlyList<TelemetryPointResponse>> RangeAsync(
        string robotId, TelemetryQuery query, CancellationToken ct = default)
    {
        if (!Aggregations.TryGetValue(query.Agg, out var fn))
            throw new ArgumentOutOfRangeException(nameof(query), query.Agg, "Unsupported aggregation.");

        var sql = fn.Length == 0
            ? "SELECT ts, value FROM telemetry WHERE robot_id = @robot AND metric = @metric "
              + "AND ts >= @from AND ts < @to ORDER BY ts"
            : $"SELECT date_trunc('minute', ts) AS ts, {fn} AS value FROM telemetry "
              + "WHERE robot_id = @robot AND metric = @metric AND ts >= @from AND ts < @to "
              + "GROUP BY 1 ORDER BY 1";

        await db.Database.OpenConnectionAsync(ct);
        try
        {
            await using var cmd = CreateCommand(sql);
            Bind(cmd, "robot", robotId);
            Bind(cmd, "metric", query.Metric);
            Bind(cmd, "from", query.From);
            Bind(cmd, "to", query.To);

            var points = new List<TelemetryPointResponse>();
            await using var reader = await cmd.ExecuteReaderAsync(ct);
            while (await reader.ReadAsync(ct))
                points.Add(new TelemetryPointResponse(reader.GetFieldValue<DateTimeOffset>(0), reader.GetDouble(1)));
            return points;
        }
        finally
        {
            await db.Database.CloseConnectionAsync();
        }
    }

    /// <summary>
    /// Bulk insert for POST /bridge/telemetry/batch.
    /// ponytail: multi row INSERT chunked at 1000 rows; move to COPY if a reconnect ever dumps
    /// an outbox large enough for this to show up in the request latency.
    /// </summary>
    public async Task<int> InsertBatchAsync(IReadOnlyList<TelemetrySample> samples, CancellationToken ct = default)
    {
        if (samples.Count == 0) return 0;

        var written = 0;
        await db.Database.OpenConnectionAsync(ct);
        try
        {
            foreach (var chunk in samples.Chunk(1000))
            {
                var sql = new StringBuilder("INSERT INTO telemetry (ts, robot_id, metric, value, tags) VALUES ");
                await using var cmd = CreateCommand(string.Empty);
                for (var i = 0; i < chunk.Length; i++)
                {
                    if (i > 0) sql.Append(',');
                    sql.Append($"(@ts{i},@robot{i},@metric{i},@value{i},@tags{i}::jsonb)");
                    Bind(cmd, $"ts{i}", chunk[i].Ts);
                    Bind(cmd, $"robot{i}", chunk[i].RobotId);
                    Bind(cmd, $"metric{i}", chunk[i].Metric);
                    Bind(cmd, $"value{i}", chunk[i].Value);
                    Bind(cmd, $"tags{i}", chunk[i].Tags?.RootElement.GetRawText());
                }
                cmd.CommandText = sql.ToString();
                written += await cmd.ExecuteNonQueryAsync(ct);
            }
            return written;
        }
        finally
        {
            await db.Database.CloseConnectionAsync();
        }
    }

    private DbCommand CreateCommand(string sql)
    {
        var cmd = db.Database.GetDbConnection().CreateCommand();
        cmd.CommandText = sql;
        cmd.Transaction = db.Database.CurrentTransaction?.GetDbTransaction();
        return cmd;
    }

    private static void Bind(DbCommand cmd, string name, object? value)
    {
        var p = cmd.CreateParameter();
        p.ParameterName = name;
        p.Value = value ?? DBNull.Value;
        cmd.Parameters.Add(p);
    }
}
