// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Neml.Api.Auth;

namespace Neml.Tests;

/// <summary>§5.5 — Argon2id, minimum 12 characters.</summary>
public sealed class PasswordPolicyTests
{
    private const string Good = "kuvvetli-sifre-2026";

    [Theory]
    [InlineData("")]
    [InlineData("kisa")]
    [InlineData("onbirkarakt")]           // 11 characters: one short of §5.5.
    public void A_password_under_twelve_characters_is_rejected(string password) =>
        Assert.Throws<ArgumentException>(() => PasswordHasher.Hash(password));

    [Fact]
    public void Exactly_twelve_characters_is_accepted()
    {
        Assert.Equal(12, PasswordHasher.MinimumLength);
        Assert.StartsWith(
            "$argon2id$", PasswordHasher.Hash(new string('a', PasswordHasher.MinimumLength)), StringComparison.Ordinal);
    }

    [Fact]
    public void A_valid_password_round_trips_as_argon2id()
    {
        var hash = PasswordHasher.Hash(Good);

        Assert.StartsWith("$argon2id$", hash, StringComparison.Ordinal);
        Assert.True(PasswordHasher.Verify(hash, Good));
        Assert.False(PasswordHasher.Verify(hash, Good + "x"));
    }

    [Fact]
    public void The_same_password_hashes_differently_every_time() =>
        Assert.NotEqual(PasswordHasher.Hash(Good), PasswordHasher.Hash(Good));

    [Fact]
    public void An_empty_stored_hash_verifies_false_instead_of_throwing() =>
        Assert.False(PasswordHasher.Verify(string.Empty, Good));
}
