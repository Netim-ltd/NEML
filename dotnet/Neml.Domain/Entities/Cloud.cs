// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using Neml.Domain.Enums;

namespace Neml.Domain.Entities;

// neml_cloud only. The lab instance (neml_local) never carries these tables.

/// <summary>Table <c>users</c>.</summary>
public class User
{
    public Guid Id { get; set; }
    public required string Email { get; set; }
    public required string PasswordHash { get; set; }       // argon2id, section 5.5
    public required UserRole Role { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
}

/// <summary>Table <c>devices</c>.</summary>
public class Device
{
    public Guid Id { get; set; }
    public required Guid UserId { get; set; }
    public required DevicePlatform Platform { get; set; }
    public string? PushToken { get; set; }
    public DateTimeOffset? LastSeen { get; set; }
}

/// <summary>Table <c>commands</c> — the queue the lab bridge drains (section 3.1).</summary>
public class Command
{
    public Guid Id { get; set; }
    public required Guid UserId { get; set; }
    public required string IdempotencyKey { get; set; }
    public long Seq { get; set; }                           // monotonic, database generated
    public required string Kind { get; set; }               // section 9.3 command types
    public required JsonDocument Payload { get; set; }
    public required CommandState State { get; set; }
    public JsonDocument? Result { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
    public DateTimeOffset? AppliedAt { get; set; }
}

/// <summary>
/// Table <c>refresh_tokens</c>. Section 5.5 mandates rotating 30 day refresh tokens but
/// section 7 declares no table for them; this is the minimum storage that satisfies it.
/// Only the SHA-256 of the token is stored, never the token itself.
/// </summary>
public class RefreshToken
{
    public Guid Id { get; set; }
    public required Guid UserId { get; set; }
    public required string TokenHash { get; set; }
    public DateTimeOffset IssuedAt { get; set; }
    public required DateTimeOffset ExpiresAt { get; set; }
    public DateTimeOffset? RevokedAt { get; set; }
    public Guid? ReplacedBy { get; set; }
}
