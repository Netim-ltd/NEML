// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Net.Http.Json;

namespace Neml.Web.Services;

/// <summary>Thin typed wrapper over the §9.3 endpoints this UI actually uses.</summary>
public sealed class ApiClient(HttpClient http)
{
    public Task<BrainStatus?> GetBrainStatusAsync(CancellationToken ct = default) =>
        http.GetFromJsonAsync<BrainStatus>("api/v1/brain/status", ct);

    public Task<Robot[]?> GetRobotsAsync(CancellationToken ct = default) =>
        http.GetFromJsonAsync<Robot[]>("api/v1/robots", ct);

    public Task<Robot?> GetRobotAsync(string id, CancellationToken ct = default) =>
        http.GetFromJsonAsync<Robot>($"api/v1/robots/{Uri.EscapeDataString(id)}", ct);

    public Task<TelemetryPoint[]?> GetRobotTelemetryAsync(
        string id, string metric, DateTimeOffset from, CancellationToken ct = default) =>
        http.GetFromJsonAsync<TelemetryPoint[]>(
            $"api/v1/robots/{Uri.EscapeDataString(id)}/telemetry?metric={Uri.EscapeDataString(metric)}&from={Uri.EscapeDataString(from.ToString("O"))}&agg=raw",
            ct);

    public async Task RequestEstopAsync(string id, string reason, CancellationToken ct = default) =>
        (await http.PostAsJsonAsync($"api/v1/robots/{Uri.EscapeDataString(id)}/estop", new { reason }, ct))
        .EnsureSuccessStatusCode();

    public async Task<IReadOnlyList<TaskItem>> GetTasksAsync(int page = 1, CancellationToken ct = default) =>
        (await http.GetFromJsonAsync<Paged<TaskItem>>($"api/v1/tasks?page={page}", ct))?.Items ?? [];

    public Task<TaskItem?> GetTaskAsync(Guid id, CancellationToken ct = default) =>
        http.GetFromJsonAsync<TaskItem>($"api/v1/tasks/{id}", ct);

    public Task<TaskRun[]?> GetTaskRunsAsync(Guid id, CancellationToken ct = default) =>
        http.GetFromJsonAsync<TaskRun[]>($"api/v1/tasks/{id}/runs", ct);

    public async Task CancelTaskAsync(Guid id, CancellationToken ct = default) =>
        (await http.PostAsJsonAsync($"api/v1/tasks/{id}/cancel", new { }, ct)).EnsureSuccessStatusCode();

    public Task<Approval[]?> GetPendingApprovalsAsync(CancellationToken ct = default) =>
        http.GetFromJsonAsync<Approval[]>("api/v1/approvals?pending=true", ct);

    public Task<Approval?> GetApprovalAsync(Guid id, CancellationToken ct = default) =>
        http.GetFromJsonAsync<Approval>($"api/v1/approvals/{id}", ct);

    public Task<HttpResponseMessage> ApproveAsync(Guid id, ApprovalDecision decision, CancellationToken ct = default) =>
        http.PostAsJsonAsync($"api/v1/approvals/{id}/approve", decision, ct);

    public Task<HttpResponseMessage> RejectAsync(Guid id, ApprovalDecision decision, CancellationToken ct = default) =>
        http.PostAsJsonAsync($"api/v1/approvals/{id}/reject", decision, ct);

    // ---- screen 4: create / reprioritise ----
    public Task<HttpResponseMessage> CreateTaskAsync(NewTask task, CancellationToken ct = default) =>
        http.PostAsJsonAsync("api/v1/tasks", task, ct);

    public Task<HttpResponseMessage> SetPriorityAsync(Guid id, decimal priority, CancellationToken ct = default) =>
        http.PatchAsJsonAsync($"api/v1/tasks/{id}", new { priority }, ct);

    // ---- screen 6: brain console ----
    public async Task<CommandAccepted?> SendBrainCommandAsync(string text, CancellationToken ct = default)
    {
        using var response = await http.PostAsJsonAsync("api/v1/brain/command", new { text }, ct);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<CommandAccepted>(ct);
    }

    public Task<CommandResult?> GetCommandAsync(Guid id, CancellationToken ct = default) =>
        http.GetFromJsonAsync<CommandResult>($"api/v1/brain/command/{id}", ct);

    /// <summary>The 3D scene of a genome; null until the lab has published it.</summary>
    public async Task<System.Text.Json.JsonElement?> GetModelSceneAsync(string genomeId, CancellationToken ct = default)
    {
        using var response = await http.GetAsync($"api/v1/models/{Uri.EscapeDataString(genomeId)}/scene", ct);
        if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return null;
        }

        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<System.Text.Json.JsonElement>(ct);
    }

    public async Task<CommandAccepted?> ChatModelAsync(string genomeId, string text, string? screen = null, CancellationToken ct = default)
    {
        using var response = await http.PostAsJsonAsync($"api/v1/models/{Uri.EscapeDataString(genomeId)}/chat", new { text, screen }, ct);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<CommandAccepted>(ct);
    }

    public async Task<CommandAccepted?> PartModelAsync(string genomeId, string part, double[]? pos, double[]? size, Dictionary<string, double>? parameters, CancellationToken ct = default)
    {
        using var response = await http.PostAsJsonAsync($"api/v1/models/{Uri.EscapeDataString(genomeId)}/part", new { part, pos, size, @params = parameters }, ct);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<CommandAccepted>(ct);
    }

    public async Task<CommandAccepted?> NotesAsync(string? forget, CancellationToken ct = default)
    {
        using var response = await http.PostAsJsonAsync("api/v1/models/notes", new { forget }, ct);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<CommandAccepted>(ct);
    }

    public async Task<CommandAccepted?> DesignModelAsync(string text, IEnumerable<object> history, CancellationToken ct = default)
    {
        using var response = await http.PostAsJsonAsync("api/v1/models/design", new { text, history }, ct);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<CommandAccepted>(ct);
    }

    public async Task<CommandAccepted?> ScanGithubAsync(string repo, CancellationToken ct = default)
    {
        using var response = await http.PostAsJsonAsync("api/v1/imports/scan", new { repo }, ct);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<CommandAccepted>(ct);
    }

    public async Task<CommandAccepted?> ImportGithubAsync(string repo, string branch, IEnumerable<string> paths, bool ack, string? genomeId, string? newName, bool all = false, CancellationToken ct = default)
    {
        using var response = await http.PostAsJsonAsync("api/v1/imports/github", new { repo, branch, paths, all, ack, genomeId, newName }, ct);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<CommandAccepted>(ct);
    }

    public async Task<CommandAccepted?> RefreshImportAsync(string genomeId, string? repo, CancellationToken ct = default)
    {
        using var response = await http.PostAsJsonAsync("api/v1/imports/refresh", new { genomeId, repo }, ct);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<CommandAccepted>(ct);
    }

    public async Task<CommandAccepted?> ArchiveModelAsync(string model, CancellationToken ct = default)
    {
        using var response = await http.PostAsync($"api/v1/models/{Uri.EscapeDataString(model)}/archive", null, ct);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<CommandAccepted>(ct);
    }

    public async Task<CommandAccepted?> PoseOpAsync(string model, string op, string? name = null, Dictionary<string, double>? values = null, CancellationToken ct = default)
    {
        using var response = await http.PostAsJsonAsync($"api/v1/models/{Uri.EscapeDataString(model)}/poses", new { op, name, values }, ct);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<CommandAccepted>(ct);
    }

    public async Task<CommandAccepted?> LearnOpAsync(object body, CancellationToken ct = default)
    {
        using var response = await http.PostAsJsonAsync("api/v1/learning", body, ct);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<CommandAccepted>(ct);
    }

    public Task<HttpResponseMessage> ApplyModelAsync(string genomeId, CancellationToken ct = default) =>
        http.PostAsync($"api/v1/models/{Uri.EscapeDataString(genomeId)}/apply", null, ct);

    public Task<BotManifestView?> GetBotManifestAsync(CancellationToken ct = default) =>
        http.GetFromJsonAsync<BotManifestView>("api/v1/bot/manifest", ct);

    public async Task<BotAccountView?> CreateBotAccountAsync(CancellationToken ct = default)
    {
        using var response = await http.PostAsync("api/v1/bot/accounts", null, ct);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<BotAccountView>(ct);
    }

    // ---- screens 7-9 ----
    public async Task<Campaign[]> GetCampaignsAsync(CancellationToken ct = default) =>
        await http.GetFromJsonAsync<Campaign[]>("api/v1/campaigns", ct) ?? [];

    public async Task<GenerationPoint[]> GetGenerationsAsync(Guid id, CancellationToken ct = default) =>
        await http.GetFromJsonAsync<GenerationPoint[]>($"api/v1/campaigns/{id}/generations", ct) ?? [];

    public async Task<Candidate[]> GetCandidatesAsync(Guid id, CancellationToken ct = default) =>
        await http.GetFromJsonAsync<Candidate[]>($"api/v1/campaigns/{id}/candidates", ct) ?? [];

    public Task<HttpResponseMessage> CreateCampaignAsync(object body, CancellationToken ct = default) =>
        http.PostAsJsonAsync("api/v1/campaigns", body, ct);

    /// <summary>Recorded simulation runs the user started from the panel (source user:web-sim).</summary>
    public async Task<TaskItem[]> GetSimRunsAsync(CancellationToken ct = default) =>
        (await http.GetFromJsonAsync<Paged<TaskItem>>("api/v1/tasks?kind=exploration&source=user:web-sim", ct))?.Items.Take(12).ToArray() ?? [];

    public Task<HttpResponseMessage> StopCampaignAsync(Guid id, CancellationToken ct = default) =>
        http.PostAsJsonAsync($"api/v1/campaigns/{id}/stop", new { }, ct);

    public async Task<GenomeNode[]> GetGenomeTreeAsync(CancellationToken ct = default) =>
        await http.GetFromJsonAsync<GenomeNode[]>("api/v1/genomes/tree", ct) ?? [];

    public async Task<Skill[]> GetSkillsAsync(CancellationToken ct = default) =>
        await http.GetFromJsonAsync<Skill[]>("api/v1/skills", ct) ?? [];

    public async Task<Skill[]> GetSkillVersionsAsync(string key, CancellationToken ct = default) =>
        await http.GetFromJsonAsync<Skill[]>($"api/v1/skills/{Uri.EscapeDataString(key)}/versions", ct) ?? [];

    // ---- screen 11: manufacturing ----
    public async Task<PrintJob[]> GetPrintJobsAsync(CancellationToken ct = default) =>
        await http.GetFromJsonAsync<PrintJob[]>("api/v1/print-jobs", ct) ?? [];

    public Task<PrinterStatus?> GetPrinterStatusAsync(string id, CancellationToken ct = default) =>
        http.GetFromJsonAsync<PrinterStatus>($"api/v1/printers/{Uri.EscapeDataString(id)}/status", ct);

    public Task<HttpResponseMessage> CancelPrintAsync(Guid id, string? reason, CancellationToken ct = default) =>
        http.PostAsJsonAsync($"api/v1/print-jobs/{id}/cancel", new { reason }, ct);

    public Task<HttpResponseMessage> SubmitQcAsync(Guid id, QcForm form, CancellationToken ct = default) =>
        http.PostAsJsonAsync($"api/v1/print-jobs/{id}/qc", form.ToWire(), ct);

    // ---- screen 12 / 13 ----
    public async Task<AuditEntry[]> GetAuditAsync(string? actor = null, string? outcome = null, CancellationToken ct = default)
    {
        var query = new List<string>();
        if (!string.IsNullOrEmpty(actor)) { query.Add($"actor={Uri.EscapeDataString(actor)}"); }
        if (!string.IsNullOrEmpty(outcome)) { query.Add($"outcome={Uri.EscapeDataString(outcome)}"); }
        var url = query.Count == 0 ? "api/v1/audit" : "api/v1/audit?" + string.Join('&', query);
        return await http.GetFromJsonAsync<AuditEntry[]>(url, ct) ?? [];
    }

    public async Task<Device[]> GetDevicesAsync(CancellationToken ct = default) =>
        await http.GetFromJsonAsync<Device[]>("api/v1/auth/devices", ct) ?? [];
}
