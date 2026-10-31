// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Neml.Api.Auth;
using Neml.Api.Contracts;
using Neml.Api.Services;
using Neml.Domain.Dtos;

namespace Neml.Api.Controllers;

/// <summary>
/// Recordings of simulation runs (GIFs the lab renders). The lab pushes them in over the bridge
/// key; people read them with a normal login. Names are content hashes, so a URL never changes
/// meaning and a name that is not exactly that shape never touches the disk.
/// </summary>
public static partial class MediaStore
{
    public const long MaxBytes = 8 * 1024 * 1024;

    [GeneratedRegex("^([0-9a-f]{24}\\.(gif|png|stl|step|svg|dxf|csv|kicad_sch|kicad_pcb|nmesh)|scene-[0-9a-f]{12}\\.json|live-[0-9a-f]{12}\\.png)$")]
    private static partial Regex NameShape();

    public static bool IsValidName(string name) => NameShape().IsMatch(name);

    public static string Directory(IConfiguration configuration) =>
        configuration["Media:Dir"] ?? Path.Combine(AppContext.BaseDirectory, "media");

    public static string ContentType(string name) => Path.GetExtension(name) switch
    {
        ".png" => "image/png",
        ".stl" => "model/stl",
        ".step" => "model/step",
        ".nmesh" => "application/x-neml-mesh",
        ".svg" => "image/svg+xml",
        ".dxf" => "image/vnd.dxf",
        ".csv" => "text/csv",
        ".kicad_sch" or ".kicad_pcb" => "text/plain",
        ".json" => "application/json",
        _ => "image/gif",
    };

    /// <summary>The live camera frame of a model: same derivation as the lab's live_name().</summary>
    public static string LiveName(string model) =>
        "live-" + Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(model)))[..12] + ".png";

    /// <summary>Where the lab stores a genome's 3D scene: a name both sides derive from the id.</summary>
    public static string SceneName(string genomeId) =>
        "scene-" + Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(genomeId)))[..12] + ".json";
}

/// <summary>Read side: the panel and the app show recordings with a signed in account.</summary>
[Route("api/v1/media")]
[Tags("Media")]
public sealed class MediaController(IConfiguration configuration) : NemlController
{
    /// <summary>One recording. The access token may travel in the query string so an image tag can load it.</summary>
    [HttpGet("{name}")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public IActionResult Get(string name)
    {
        var path = Path.Combine(MediaStore.Directory(configuration), name);
        if (!MediaStore.IsValidName(name) || !System.IO.File.Exists(path))
        {
            return NotFound();
        }

        // Content-hash names never change; the live frame and the scene are replaced in place.
        Response.Headers.CacheControl = name.StartsWith("live-", StringComparison.Ordinal)
            ? "no-store"
            : "private, max-age=86400, immutable";
        return PhysicalFile(path, MediaStore.ContentType(name));
    }
}

/// <summary>What the lab learns from its own failures: lessons to accept, the small models trained from them.</summary>
[Route("api/v1/learning")]
[Tags("Learning")]
public sealed class LearningController(CommandQueue queue, IAuthorizationService authorization) : NemlController
{
    /// <summary>One operation: state, decide (id + accepted/rejected), note (domain + text), design (brief) gateway (action list/set/rotate/remove + name + limits; owner only) or cad (tool fit|standard_part|drawing|build_recipe|fem|assemble + args).</summary>
    [HttpPost]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Op(LearnRequest request, CancellationToken ct)
    {
        // The language model door's keys and limits (op "gateway") decide who may use the lab's model: owner only.
        if (request.Op == "gateway" && !(await authorization.AuthorizeAsync(User, Policies.Owner)).Succeeded)
        {
            return Forbid();
        }

        var payload = System.Text.Json.JsonSerializer.Serialize(request, System.Text.Json.JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.LearnOp, payload, IdempotencyKey(), ct));
    }
}

/// <summary>POST /learning</summary>
public record LearnRequest(string Op, string? Id, string? Decision, string? Domain, string? Kind, string? Text, Dictionary<string, string>? Context, string? Template = null, int? Difficulty = null, int? Seed = null, string? Brief = null, string? Action = null, string? Name = null, int? MaxTokens = null, int? DailyTokens = null, int? Priority = null, string? Tool = null, System.Text.Json.JsonElement? Args = null);

/// <summary>The robot models: the 3D scene (parts, internals, bill of materials) of a genome.</summary>
[Route("api/v1/models")]
[Tags("Models")]
public sealed class ModelsController(IConfiguration configuration, CommandQueue queue) : NemlController
{
    /// <summary>
    /// Says what to change in plain language ("make the leg 10 mm longer"). The lab's model turns it
    /// into a draft design that never replaces the active one by itself.
    /// </summary>
    [HttpPost("{genomeId}/chat")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Chat(string genomeId, ModelChatRequest request, CancellationToken ct)
    {
        // Spec 5.4: the text is untrusted data, forwarded verbatim and never read here.
        var payload = System.Text.Json.JsonSerializer.Serialize(new { genomeId, text = request.Text, screen = request.Screen }, System.Text.Json.JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.ModelChat, payload, IdempotencyKey(), ct));
    }

    /// <summary>Asks the owner (level 4 approval) to make a draft design the active one.</summary>
    [HttpPost("{genomeId}/apply")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Apply(string genomeId, CancellationToken ct)
    {
        var payload = System.Text.Json.JsonSerializer.Serialize(new { genomeId }, System.Text.Json.JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.ModelApply, payload, IdempotencyKey(), ct));
    }

    /// <summary>Hides a model's drafts and tests (they become deprecated); a model with an active design stays.</summary>
    [HttpPost("{model}/archive")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Archive(string model, CancellationToken ct)
    {
        var payload = System.Text.Json.JsonSerializer.Serialize(new { name = model }, System.Text.Json.JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.ModelArchive, payload, IdempotencyKey(), ct));
    }

    /// <summary>The named joint poses of a model: list, save (name + values) or delete (name).</summary>
    [HttpPost("{model}/poses")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Poses(string model, PoseRequest request, CancellationToken ct)
    {
        var payload = System.Text.Json.JsonSerializer.Serialize(new { model, op = request.Op, name = request.Name, values = request.Values }, System.Text.Json.JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.PoseOp, payload, IdempotencyKey(), ct));
    }

    /// <summary>
    /// The new-model assistant: describe the robot you want (with the conversation so far); the lab
    /// asks one more question or answers with a draft design of its own name.
    /// </summary>
    [HttpPost("design")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Design(ModelDesignRequest request, CancellationToken ct)
    {
        var payload = System.Text.Json.JsonSerializer.Serialize(new { text = request.Text, history = request.History ?? [] }, System.Text.Json.JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.ModelDesign, payload, IdempotencyKey(), ct));
    }

    /// <summary>Changes one part of a draft-to-be: its position, box size or printed-part dimensions.</summary>
    [HttpPost("{genomeId}/part")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Part(string genomeId, ModelPartRequest request, CancellationToken ct)
    {
        var payload = System.Text.Json.JsonSerializer.Serialize(
            new { genomeId, part = request.Part, pos = request.Pos, size = request.Size, @params = request.Params },
            System.Text.Json.JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.ModelPart, payload, IdempotencyKey(), ct));
    }

    /// <summary>The design notes the lab learned from the web (optionally forgetting one).</summary>
    [HttpPost("notes")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Notes(ModelNotesRequest request, CancellationToken ct)
    {
        var payload = System.Text.Json.JsonSerializer.Serialize(new { forget = request.Forget }, System.Text.Json.JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.ModelNotes, payload, IdempotencyKey(), ct));
    }

    /// <summary>The latest camera frame of a recorded simulation run of this model (replaced in place).</summary>
    [HttpGet("{model}/live")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public IActionResult Live(string model)
    {
        var path = Path.Combine(MediaStore.Directory(configuration), MediaStore.LiveName(model));
        if (!System.IO.File.Exists(path))
        {
            return NotFound();
        }

        Response.Headers.CacheControl = "no-store";
        return PhysicalFile(path, "image/png");
    }

    /// <summary>The scene the lab rendered for this genome; 404 until the lab has published it.</summary>
    [HttpGet("{genomeId}/scene")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public IActionResult Scene(string genomeId)
    {
        var path = Path.Combine(MediaStore.Directory(configuration), MediaStore.SceneName(genomeId));
        if (!System.IO.File.Exists(path))
        {
            return NotFound();
        }

        Response.Headers.CacheControl = "no-cache";
        return PhysicalFile(path, "application/json");
    }
}

/// <summary>POST /models/{genomeId}/chat</summary>
public record ModelChatRequest(string Text, string? Screen);

/// <summary>POST /models/{model}/poses</summary>
public record PoseRequest(string Op, string? Name, Dictionary<string, double>? Values);

/// <summary>POST /models/design</summary>
public record ModelDesignRequest(string Text, ModelDesignTurn[]? History);

/// <summary>One earlier turn of the new-model conversation.</summary>
public record ModelDesignTurn(string Role, string Text);

/// <summary>POST /models/{genomeId}/part</summary>
public record ModelPartRequest(string Part, double[]? Pos, double[]? Size, Dictionary<string, double>? Params);

/// <summary>POST /models/notes</summary>
public record ModelNotesRequest(string? Forget);
