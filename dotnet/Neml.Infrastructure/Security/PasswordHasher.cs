// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Isopoh.Cryptography.Argon2;

namespace Neml.Infrastructure.Security;

/// <summary>Section 5.5: Argon2id, minimum 12 characters. The salt rides inside the encoded hash.</summary>
public static class PasswordHasher
{
    public const int MinimumLength = 12;

    public static string Hash(string password)
    {
        ArgumentNullException.ThrowIfNull(password);
        if (password.Length < MinimumLength)
            throw new ArgumentException($"Password must be at least {MinimumLength} characters.", nameof(password));

        return Argon2.Hash(password, type: Argon2Type.HybridAddressing);
    }

    /// <summary>False for a wrong password and for a malformed stored hash alike.</summary>
    public static bool Verify(string encodedHash, string password) =>
        !string.IsNullOrEmpty(encodedHash) && !string.IsNullOrEmpty(password) && Argon2.Verify(encodedHash, password);
}
