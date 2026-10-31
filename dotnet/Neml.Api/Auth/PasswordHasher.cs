// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

namespace Neml.Api.Auth;

/// <summary>
/// Spec 5.5 passwords: Argon2id, minimum 12 characters. The parameters are defined once, in
/// Neml.Infrastructure.Security.PasswordHasher; this is the name the API and its tests reach
/// for, and it forwards. No second hashing configuration exists.
/// </summary>
public static class PasswordHasher
{
    public const int MinimumLength = Infrastructure.Security.PasswordHasher.MinimumLength;

    public static string Hash(string password) => Infrastructure.Security.PasswordHasher.Hash(password);

    public static bool Verify(string encodedHash, string password) =>
        Infrastructure.Security.PasswordHasher.Verify(encodedHash, password);
}
