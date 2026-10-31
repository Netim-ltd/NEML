// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;

namespace Neml.Api.Auth;

/// <summary>
/// HS256 access tokens with a 15 minute lifetime, and the random string behind a refresh
/// token (spec 5.5). Only the SHA-256 of that string is stored, by
/// Neml.Infrastructure.Security.RefreshTokenStore.
/// </summary>
public sealed class JwtIssuer
{
    public const int AccessTokenMinutes = 15;

    private readonly SigningCredentials _credentials;
    private readonly string _issuer;
    private readonly string _audience;

    public JwtIssuer(IConfiguration configuration)
    {
        var section = configuration.GetSection("Jwt");
        var key = section["Key"] ?? throw new InvalidOperationException("Jwt:Key is not configured.");
        if (Encoding.UTF8.GetByteCount(key) < 32)
        {
            throw new InvalidOperationException("Jwt:Key must be at least 32 bytes for HS256.");
        }

        _credentials = new SigningCredentials(
            new SymmetricSecurityKey(Encoding.UTF8.GetBytes(key)), SecurityAlgorithms.HmacSha256);
        _issuer = section["Issuer"] ?? "neml";
        _audience = section["Audience"] ?? "neml-clients";
    }

    public TokenValidationParameters ValidationParameters => new()
    {
        ValidateIssuer = true,
        ValidateAudience = true,
        ValidateLifetime = true,
        ValidateIssuerSigningKey = true,
        ValidIssuer = _issuer,
        ValidAudience = _audience,
        IssuerSigningKey = _credentials.Key,
        RoleClaimType = ClaimTypes.Role,
        NameClaimType = JwtRegisteredClaimNames.Sub,
        ClockSkew = TimeSpan.FromSeconds(30),
    };

    public static string NewRefreshToken() => Base64UrlEncoder.Encode(RandomNumberGenerator.GetBytes(32));

    public string CreateAccessToken(Guid userId, string email, string role) =>
        new JsonWebTokenHandler().CreateToken(new SecurityTokenDescriptor
        {
            Issuer = _issuer,
            Audience = _audience,
            Expires = DateTime.UtcNow.AddMinutes(AccessTokenMinutes),
            SigningCredentials = _credentials,
            Subject = new ClaimsIdentity(
            [
                new Claim(JwtRegisteredClaimNames.Sub, userId.ToString()),
                new Claim(JwtRegisteredClaimNames.Email, email),
                new Claim(ClaimTypes.Role, role),
            ]),
        });
}
