// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;

namespace Neml.Cli;

/// <summary>
/// The §5.5 JWT pair plus the server it belongs to, cached in the user profile directory so a
/// command does not have to log in again. One process, one file: no locking needed.
/// </summary>
public sealed record Session(string Server, string Access, string Refresh)
{
    private static readonly JsonSerializerOptions Options = new() { WriteIndented = true };

    public static string Path { get; set; } = System.IO.Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        ".neml",
        "session.json");

    public static Session? Load()
    {
        try
        {
            return File.Exists(Path)
                ? JsonSerializer.Deserialize<Session>(File.ReadAllText(Path))
                : null;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    public void Save()
    {
        var directory = System.IO.Path.GetDirectoryName(Path)!;
        Directory.CreateDirectory(directory);
        File.WriteAllText(Path, JsonSerializer.Serialize(this, Options));

        if (!OperatingSystem.IsWindows())
        {
            // Tokens are bearer credentials: keep them off other accounts on the box.
            File.SetUnixFileMode(Path, UnixFileMode.UserRead | UnixFileMode.UserWrite);
        }
    }

    public static void Clear()
    {
        if (File.Exists(Path))
        {
            File.Delete(Path);
        }
    }
}
