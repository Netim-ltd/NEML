// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Metadata;
using Neml.Infrastructure.Persistence;

namespace Neml.Tests;

/// <summary>
/// The ADR-011 DDL, checked against the EF model. §7's schema is shared, so skill_runs and
/// budget_usage exist twice — here and in Alembic 0003 for neml_local — and the mirror only
/// holds while the column list, the types, the composite key and the CHECK agree. The model
/// is read without opening a connection, so this runs whether or not Docker is up.
/// </summary>
public sealed class InfrastructureSchemaTests
{
    private static readonly IModel Model = BuildModel();

    /// <summary>One row per ADR-011 column: table, column, store type, nullable.</summary>
    public static TheoryData<string, string, string, bool> Columns =>
        new()
        {
            { "skill_runs", "id", "bigint", false },
            { "skill_runs", "skill_id", "text", false },
            { "skill_runs", "task_run_id", "bigint", true },
            { "skill_runs", "env", "text", false },
            { "skill_runs", "seed", "bigint", true },
            { "skill_runs", "success", "boolean", false },
            { "skill_runs", "failure_mode", "text", true },
            { "skill_runs", "deterministic", "boolean", false },
            { "skill_runs", "run_at", "timestamp with time zone", false },
            { "budget_usage", "day", "date", false },
            { "budget_usage", "resource", "text", false },
            { "budget_usage", "used", "numeric(14,4)", false },
        };

    [Theory]
    [MemberData(nameof(Columns))]
    public void Every_ADR_011_column_is_mapped_with_its_declared_type(
        string table, string column, string storeType, bool nullable)
    {
        var property = Assert.Single(Properties(table), p => p.GetColumnName() == column);

        Assert.Equal(storeType, property.GetColumnType());
        Assert.Equal(nullable, property.IsNullable);
    }

    /// <summary>The other direction: a column the ADR does not declare is drift too.</summary>
    [Theory]
    [InlineData("skill_runs")]
    [InlineData("budget_usage")]
    public void Neither_table_carries_a_column_the_ADR_does_not_declare(string table) =>
        Assert.Equal(
            Columns.Cast<object[]>().Where(row => (string)row[0] == table).Select(row => (string)row[1]).Order(),
            Properties(table).Select(p => p.GetColumnName()).Order());

    [Fact]
    public void Budget_usage_is_keyed_by_day_and_resource_together()
    {
        var key = Assert.Single(Entity("budget_usage").GetKeys());

        Assert.Equal(["day", "resource"], key.Properties.Select(p => p.GetColumnName()));
        Assert.Equal("pk_budget_usage", key.GetName());

        // Reset is implicit: a new day is a new row, so used has to start at zero by itself.
        Assert.Equal("0", Property("budget_usage", "used").GetDefaultValueSql());
    }

    [Fact]
    public void Skill_runs_env_allows_exactly_the_two_ADR_011_values()
    {
        var check = Assert.Single(Entity("skill_runs").GetCheckConstraints());

        Assert.Equal("ck_skill_runs_env", check.Name);
        Assert.Equal("env IN ('sim','real')", check.Sql);
    }

    [Fact]
    public void Failure_mode_is_a_bare_string_because_section_7_puts_no_CHECK_on_it()
    {
        // ADR-013 fixes the ten modes in the brain profile, not in the database. An enum here
        // would refuse a row PostgreSQL accepts, and would be a second copy of that list.
        var property = Property("skill_runs", "failure_mode");

        Assert.Equal(typeof(string), property.ClrType);
        Assert.Null(property.GetValueConverter());
    }

    [Fact]
    public void Skill_runs_is_indexed_by_skill_and_newest_run_first()
    {
        var index = Assert.Single(Entity("skill_runs").GetIndexes(), i => i.Properties.Count == 2);

        Assert.Equal(["skill_id", "run_at"], index.Properties.Select(p => p.GetColumnName()));
        Assert.Equal([false, true], index.IsDescending!);
    }

    [Fact]
    public void Skill_runs_references_skills_and_task_runs()
    {
        var foreignKeys = Entity("skill_runs")
            .GetForeignKeys()
            .ToDictionary(f => f.PrincipalEntityType.GetTableName()!);

        Assert.Equal(["skills", "task_runs"], foreignKeys.Keys.Order());
        Assert.True(foreignKeys["skills"].IsRequired);          // skill_id is NOT NULL
        Assert.False(foreignKeys["task_runs"].IsRequired);      // task_run_id is not
        Assert.All(foreignKeys.Values, f => Assert.Equal(DeleteBehavior.NoAction, f.DeleteBehavior));
    }

    private static IEntityType Entity(string table) =>
        Assert.Single(Model.GetEntityTypes(), e => e.GetTableName() == table);

    private static IEnumerable<IProperty> Properties(string table) => Entity(table).GetProperties();

    private static IProperty Property(string table, string column) =>
        Properties(table).Single(p => p.GetColumnName() == column);

    private static IModel BuildModel()
    {
        // The design time model, not DbContext.Model: the read optimized runtime model drops
        // the index direction and the default value sql this file is here to assert.
        using var db = new NemlDbContextFactory().CreateDbContext([]);
        return db.GetService<IDesignTimeModel>().Model;
    }
}
