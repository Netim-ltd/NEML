// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.RegularExpressions;
using Microsoft.EntityFrameworkCore;
using Neml.Domain.Entities;
using Neml.Domain.Enums;

namespace Neml.Infrastructure.Persistence;

/// <summary>
/// The neml_cloud schema of NEML_SPEC.md section 7: the mirror tables plus the cloud only
/// users, devices and commands. Column names are snake_case, produced by one pass at the end
/// of OnModelCreating instead of a naming convention package.
/// </summary>
/// <remarks>
/// Two deliberate divergences from the section 7 "the schema is shared" rule, recorded here
/// because the schema is the contract and a silent difference is the expensive kind:
/// <list type="bullet">
/// <item>
/// <description>
/// memory_chunks is NOT mirrored. It is the pgvector RAG store written by the lab embedding
/// path (section 4.6, CPU, on the lab box) and read only by lab agents. Mirroring it would put
/// the vector extension, a 384 dimension column and an HNSW index on the cloud instance for
/// rows nothing on this side ever queries. If a cloud feature ever needs semantic search,
/// add the entity plus a pgvector mapping then, not before.
/// </description>
/// </item>
/// <item>
/// <description>
/// refresh_tokens is ADDED. Section 7 does not declare it; section 5.5 requires refresh token
/// rotation for the mobile and web clients, which needs somewhere to store and revoke them.
/// It is cloud only by nature: the lab never authenticates a human.
/// </description>
/// </item>
/// </list>
/// </remarks>
public class NemlDbContext(DbContextOptions<NemlDbContext> options) : DbContext(options)
{
    public DbSet<Genome> Genomes => Set<Genome>();
    public DbSet<Robot> Robots => Set<Robot>();
    public DbSet<Skill> Skills => Set<Skill>();
    public DbSet<SkillValidation> SkillValidations => Set<SkillValidation>();
    public DbSet<SkillRun> SkillRuns => Set<SkillRun>();
    public DbSet<TaskItem> Tasks => Set<TaskItem>();
    public DbSet<TaskRun> TaskRuns => Set<TaskRun>();
    public DbSet<Campaign> Campaigns => Set<Campaign>();
    public DbSet<Candidate> Candidates => Set<Candidate>();
    public DbSet<SimRun> SimRuns => Set<SimRun>();
    public DbSet<Artifact> Artifacts => Set<Artifact>();
    public DbSet<PrintJob> PrintJobs => Set<PrintJob>();
    public DbSet<BomItem> BomItems => Set<BomItem>();
    public DbSet<Telemetry> Telemetry => Set<Telemetry>();
    public DbSet<BudgetUsage> BudgetUsage => Set<BudgetUsage>();
    public DbSet<Approval> Approvals => Set<Approval>();
    public DbSet<SafetyCheck> SafetyChecks => Set<SafetyCheck>();
    public DbSet<AuditLogEntry> AuditLog => Set<AuditLogEntry>();
    public DbSet<User> Users => Set<User>();
    public DbSet<Device> Devices => Set<Device>();
    public DbSet<Command> Commands => Set<Command>();
    public DbSet<RefreshToken> RefreshTokens => Set<RefreshToken>();

    protected override void OnModelCreating(ModelBuilder b)
    {
        b.HasPostgresExtension("pgcrypto");                 // gen_random_uuid()

        // ---------- ROBOT & GENOME ----------
        b.Entity<Genome>(e =>
        {
            e.Property(x => x.Status).HasConversion(PgEnum.Converter<GenomeStatus>());
            e.Property(x => x.FitnessScore).HasPrecision(6, 4);
            e.Property(x => x.CreatedAt).HasDefaultValueSql("now()");
            e.HasIndex(x => x.Hash).IsUnique();
            e.HasIndex(x => x.Status);
            e.HasIndex(x => x.ParentId);
            e.HasOne<Genome>().WithMany().HasForeignKey(x => x.ParentId);
            e.ToTable(t => t.HasCheckConstraint("ck_genomes_status", PgEnum.Check<GenomeStatus>("status")));
        });

        b.Entity<Robot>(e =>
        {
            e.Property(x => x.State).HasConversion(PgEnum.Converter<RobotState>());
            e.Property(x => x.BatterySoc).HasPrecision(4, 3);
            e.Property(x => x.RealityGap).HasPrecision(5, 4);
            e.Property(x => x.CreatedAt).HasDefaultValueSql("now()");
            e.HasIndex(x => x.Namespace).IsUnique();
            e.HasOne<Genome>().WithMany().HasForeignKey(x => x.GenomeId).IsRequired();
            e.ToTable(t => t.HasCheckConstraint("ck_robots_state", PgEnum.Check<RobotState>("state")));
        });

        // ---------- SKILL ----------
        b.Entity<Skill>(e =>
        {
            e.Property(x => x.Status).HasConversion(PgEnum.Converter<SkillStatus>());
            e.Property(x => x.CreatedAt).HasDefaultValueSql("now()");
            e.HasIndex(x => new { x.SkillKey, x.Version }).IsUnique();
            e.HasOne<Genome>().WithMany().HasForeignKey(x => x.GenomeId).IsRequired();
            e.HasOne<Skill>().WithMany().HasForeignKey(x => x.Supersedes);
            e.ToTable(t => t.HasCheckConstraint("ck_skills_status", PgEnum.Check<SkillStatus>("status")));
        });

        b.Entity<SkillValidation>(e =>
        {
            e.Property(x => x.Env).HasConversion(PgEnum.Converter<ValidationEnv>());
            e.Property(x => x.Ci95Low).HasPrecision(5, 4);
            e.Property(x => x.Ci95High).HasPrecision(5, 4);
            e.Property(x => x.FailureModes).HasDefaultValueSql("'[]'").IsRequired();
            e.Property(x => x.RunAt).HasDefaultValueSql("now()");
            e.HasOne<Skill>().WithMany().HasForeignKey(x => x.SkillId).IsRequired();
            e.ToTable(t =>
            {
                t.HasCheckConstraint("ck_skill_validations_env", PgEnum.Check<ValidationEnv>("env"));
                t.HasCheckConstraint("ck_skill_validations_trials", "trials > 0");
            });
        });

        // skill_runs.env carries the same two values skill_validations.env does, so it reuses
        // the same enum rather than declaring a second copy of one CHECK. failure_mode stays a
        // bare string: ADR-013 fixes the ten modes in the brain profile, section 7 puts no
        // CHECK on the column, and an enum here would refuse a row PostgreSQL accepts.
        b.Entity<SkillRun>(e =>
        {
            e.Property(x => x.Env).HasConversion(PgEnum.Converter<ValidationEnv>());
            e.Property(x => x.Deterministic).HasDefaultValue(true);
            e.Property(x => x.RunAt).HasDefaultValueSql("now()");
            e.HasIndex(x => new { x.SkillId, x.RunAt }).IsDescending(false, true);
            e.HasOne<Skill>().WithMany().HasForeignKey(x => x.SkillId).IsRequired();
            e.HasOne<TaskRun>().WithMany().HasForeignKey(x => x.TaskRunId);
            e.ToTable(t => t.HasCheckConstraint("ck_skill_runs_env", PgEnum.Check<ValidationEnv>("env")));
        });

        // ---------- TASK ----------
        b.Entity<TaskItem>(e =>
        {
            e.Property(x => x.Id).HasDefaultValueSql("gen_random_uuid()");
            e.Property(x => x.Kind).HasConversion(PgEnum.Converter<TaskKind>());
            e.Property(x => x.State).HasConversion(PgEnum.Converter<TaskState>());
            e.Property(x => x.Priority).HasPrecision(6, 3);
            e.Property(x => x.CreatedAt).HasDefaultValueSql("now()");
            e.Property(x => x.UpdatedAt).HasDefaultValueSql("now()");
            e.HasIndex(x => new { x.State, x.Priority }).IsDescending(false, true);
            e.HasOne<Robot>().WithMany().HasForeignKey(x => x.RobotId);
            e.ToTable(t =>
            {
                t.HasCheckConstraint("ck_tasks_kind", PgEnum.Check<TaskKind>("kind"));
                t.HasCheckConstraint("ck_tasks_state", PgEnum.Check<TaskState>("state"));
            });
        });

        b.Entity<TaskRun>(e =>
        {
            e.Property(x => x.Env).HasConversion(PgEnum.Converter<TaskRunEnv>());
            e.Property(x => x.Outcome).HasConversion(PgEnum.Converter<TaskOutcome>());
            e.HasIndex(x => new { x.TaskId, x.Attempt }).IsUnique();
            e.HasOne<TaskItem>().WithMany().HasForeignKey(x => x.TaskId).IsRequired();
            e.ToTable(t =>
            {
                t.HasCheckConstraint("ck_task_runs_env", PgEnum.Check<TaskRunEnv>("env"));
                t.HasCheckConstraint("ck_task_runs_outcome", PgEnum.Check<TaskOutcome>("outcome"));
            });
        });

        // ---------- EVOLUTION ----------
        b.Entity<Campaign>(e =>
        {
            e.Property(x => x.Id).HasDefaultValueSql("gen_random_uuid()");
            e.Property(x => x.State).HasConversion(PgEnum.Converter<CampaignState>());
            e.Property(x => x.StartedAt).HasDefaultValueSql("now()");
            e.ToTable(t => t.HasCheckConstraint("ck_campaigns_state", PgEnum.Check<CampaignState>("state")));
        });

        b.Entity<Candidate>(e =>
        {
            e.Property(x => x.Id).HasDefaultValueSql("gen_random_uuid()");
            e.Property(x => x.Operator).HasConversion(PgEnum.Converter<CandidateOperator>());
            e.Property(x => x.Verdict).HasConversion(PgEnum.Converter<CandidateVerdict>());
            e.Property(x => x.Fitness).HasPrecision(6, 4);
            e.Property(x => x.CreatedAt).HasDefaultValueSql("now()");
            e.HasOne<Campaign>().WithMany().HasForeignKey(x => x.CampaignId).IsRequired();
            e.HasOne<Genome>().WithMany().HasForeignKey(x => x.GenomeId).IsRequired();
            e.ToTable(t =>
            {
                t.HasCheckConstraint("ck_candidates_operator", PgEnum.Check<CandidateOperator>("operator"));
                t.HasCheckConstraint("ck_candidates_verdict", PgEnum.Check<CandidateVerdict>("verdict"));
            });
        });

        b.Entity<SimRun>(e =>
        {
            e.Property(x => x.Profile).HasConversion(PgEnum.Converter<SimProfile>());
            e.Property(x => x.DurationS).HasPrecision(8, 2);
            e.Property(x => x.Deterministic).HasDefaultValue(true);
            e.Property(x => x.RunAt).HasDefaultValueSql("now()");
            e.HasOne<Candidate>().WithMany().HasForeignKey(x => x.CandidateId);
            e.ToTable(t => t.HasCheckConstraint("ck_sim_runs_profile", PgEnum.Check<SimProfile>("profile")));
        });

        // ---------- MANUFACTURING ----------
        b.Entity<Artifact>(e =>
        {
            e.Property(x => x.Id).HasDefaultValueSql("gen_random_uuid()");
            e.Property(x => x.Kind).HasConversion(PgEnum.Converter<ArtifactKind>());
            e.Property(x => x.CreatedAt).HasDefaultValueSql("now()");
            e.HasOne<Genome>().WithMany().HasForeignKey(x => x.GenomeId);
            e.ToTable(t => t.HasCheckConstraint("ck_artifacts_kind", PgEnum.Check<ArtifactKind>("kind")));
        });

        b.Entity<PrintJob>(e =>
        {
            e.Property(x => x.Id).HasDefaultValueSql("gen_random_uuid()");
            e.Property(x => x.State).HasConversion(PgEnum.Converter<PrintJobState>());
            e.Property(x => x.EstTimeH).HasPrecision(6, 2);
            e.Property(x => x.EstFilamentG).HasPrecision(8, 2);
            e.Property(x => x.EstCostTry).HasPrecision(10, 2);
            e.HasOne<Artifact>().WithMany().HasForeignKey(x => x.ArtifactId).IsRequired();
            // approval_id carries no FK in section 7; it stays a bare UUID on purpose.
            e.ToTable(t => t.HasCheckConstraint("ck_print_jobs_state", PgEnum.Check<PrintJobState>("state")));
        });

        b.Entity<BomItem>(e =>
        {
            e.Property(x => x.UnitCostTry).HasPrecision(10, 2);
            e.HasOne<Genome>().WithMany().HasForeignKey(x => x.GenomeId).IsRequired();
        });

        // ---------- TELEMETRY ----------
        // Keyless and PARTITION BY RANGE (ts): EF can describe neither the partitioning nor the
        // monthly children, so the table, its index and the first partitions are raw SQL inside
        // the Initial migration. scripts/db/create_partitions.sh owns every later month.
        b.Entity<Telemetry>(e =>
        {
            e.HasNoKey();
            e.ToTable("telemetry", t => t.ExcludeFromMigrations());
        });

        // ---------- BUDGET (§14.4) ----------
        b.Entity<BudgetUsage>(e =>
        {
            e.HasKey(x => new { x.Day, x.Resource });
            e.Property(x => x.Used).HasPrecision(14, 4).HasDefaultValueSql("0");
        });

        // ---------- SAFETY & AUDIT ----------
        b.Entity<Approval>(e =>
        {
            e.Property(x => x.Id).HasDefaultValueSql("gen_random_uuid()");
            e.Property(x => x.Decision).HasConversion(PgEnum.Converter<ApprovalDecision>());
            e.Property(x => x.RequestedAt).HasDefaultValueSql("now()");
            e.ToTable(t =>
            {
                t.HasCheckConstraint("ck_approvals_level", "level BETWEEN 1 AND 4");
                t.HasCheckConstraint("ck_approvals_decision", PgEnum.Check<ApprovalDecision>("decision"));
            });
        });

        b.Entity<SafetyCheck>(e =>
        {
            e.Property(x => x.PerformedAt).HasDefaultValueSql("now()");
            e.HasOne<Robot>().WithMany().HasForeignKey(x => x.RobotId).IsRequired();
        });

        b.Entity<AuditLogEntry>(e =>
        {
            e.Property(x => x.Ts).HasDefaultValueSql("now()");
            e.HasIndex(x => x.Ts).IsDescending();
            e.HasOne<Approval>().WithMany().HasForeignKey(x => x.ApprovalId);
        });

        // ---------- neml_cloud ONLY ----------
        b.Entity<User>(e =>
        {
            e.Property(x => x.Id).HasDefaultValueSql("gen_random_uuid()");
            e.Property(x => x.Role).HasConversion(PgEnum.Converter<UserRole>());
            e.Property(x => x.CreatedAt).HasDefaultValueSql("now()");
            e.HasIndex(x => x.Email).IsUnique();
            e.ToTable(t => t.HasCheckConstraint("ck_users_role", PgEnum.Check<UserRole>("role")));
        });

        b.Entity<Device>(e =>
        {
            e.Property(x => x.Id).HasDefaultValueSql("gen_random_uuid()");
            e.Property(x => x.Platform).HasConversion(PgEnum.Converter<DevicePlatform>());
            e.HasOne<User>().WithMany().HasForeignKey(x => x.UserId).IsRequired();
            e.ToTable(t => t.HasCheckConstraint("ck_devices_platform", PgEnum.Check<DevicePlatform>("platform")));
        });

        b.Entity<Command>(e =>
        {
            e.Property(x => x.Id).HasDefaultValueSql("gen_random_uuid()");
            e.Property(x => x.Seq).ValueGeneratedOnAdd().UseIdentityByDefaultColumn();
            e.Property(x => x.State).HasConversion(PgEnum.Converter<CommandState>());
            e.Property(x => x.CreatedAt).HasDefaultValueSql("now()");
            e.HasIndex(x => x.IdempotencyKey).IsUnique();
            e.HasIndex(x => new { x.State, x.Seq });
            e.HasOne<User>().WithMany().HasForeignKey(x => x.UserId).IsRequired();
            e.ToTable(t => t.HasCheckConstraint("ck_commands_state", PgEnum.Check<CommandState>("state")));
        });

        b.Entity<RefreshToken>(e =>
        {
            e.Property(x => x.Id).HasDefaultValueSql("gen_random_uuid()");
            e.Property(x => x.IssuedAt).HasDefaultValueSql("now()");
            e.HasIndex(x => x.TokenHash).IsUnique();
            e.HasOne<User>().WithMany().HasForeignKey(x => x.UserId).IsRequired();
        });

        ToSnakeCase(b);
    }

    /// <summary>
    /// Rewrites every table, column, key, foreign key and index name to snake_case so the model
    /// lands exactly on the section 7 SQL. DbSet names already pluralise correctly
    /// (SkillValidations to skill_validations, AuditLog to audit_log). Delete behaviour is
    /// forced to NO ACTION here too: section 7 declares bare REFERENCES, and a lab record must
    /// never disappear because its genome was removed.
    /// </summary>
    private static void ToSnakeCase(ModelBuilder b)
    {
        foreach (var entity in b.Model.GetEntityTypes())
        {
            if (entity.GetTableName() is { } table) entity.SetTableName(Snake(table));
            foreach (var p in entity.GetProperties()) p.SetColumnName(Snake(p.Name));
            foreach (var k in entity.GetKeys()) k.SetName(Snake(k.GetName()!));
            foreach (var i in entity.GetIndexes()) i.SetDatabaseName(Snake(i.GetDatabaseName()!));
            foreach (var f in entity.GetForeignKeys())
            {
                f.SetConstraintName(Snake(f.GetConstraintName()!));
                f.DeleteBehavior = DeleteBehavior.NoAction;
            }
        }
    }

    private static string Snake(string name) =>
        Regex.Replace(name, "([a-z0-9])([A-Z])", "$1_$2").ToLowerInvariant();
}
