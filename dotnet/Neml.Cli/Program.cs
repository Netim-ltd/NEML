// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.CommandLine;
using System.Text;
using System.Text.Json;
using Neml.Cli;

var serverOption = new Option<string>("--server", "-s")
{
    Description = "Uzak API adresi (örn. https://neml.example.com)",
    DefaultValueFactory = _ => "http://localhost:5000",
};
var emailOption = new Option<string>("--email", "-e") { Description = "E-posta", Required = true };
var passwordOption = new Option<string?>("--password", "-p") { Description = "Şifre (boş bırakılırsa sorulur)" };
var stateOption = new Option<string?>("--state") { Description = "Görev durumu filtresi" };
var noteOption = new Option<string?>("--note", "-n") { Description = "Karar notu" };
var confirmOption = new Option<string?>("--confirm")
{
    Description = "Seviye 4 için doğrulama metni (ONAYLIYORUM)",
};
var taskIdArgument = new Argument<Guid>("id") { Description = "Görev kimliği" };
var approvalIdArgument = new Argument<Guid>("id") { Description = "Onay kimliği" };

var login = new Command("login", "Giriş yap ve oturumu önbelleğe al");
login.Options.Add(serverOption);
login.Options.Add(emailOption);
login.Options.Add(passwordOption);
login.SetAction(async (parse, _) =>
{
    var password = parse.GetValue(passwordOption) ?? Prompt();
    if (password.Length == 0)
    {
        Console.Error.WriteLine("Şifre gerekli.");
        return 2;
    }

    try
    {
        var session = await CliApi.LoginAsync(parse.GetValue(serverOption)!, parse.GetValue(emailOption)!, password);
        session.Save();
        Console.WriteLine($"Giriş başarılı. Oturum: {Session.Path}");
        return 0;
    }
    catch (HttpRequestException ex)
    {
        Console.Error.WriteLine($"Giriş başarısız: {ex.Message}");
        return 1;
    }
});

var logout = new Command("logout", "Oturumu kapat ve önbelleği sil");
logout.SetAction(async (_, _) => await WithApi(async api =>
{
    await api.LogoutAsync();
    Console.WriteLine("Oturum kapatıldı.");
    return 0;
}));

var status = new Command("status", "Beyin ve robot durumunu göster");
status.SetAction(async (_, _) => await WithApi(async api =>
{
    var brain = await api.GetBrainStatusAsync();
    Console.WriteLine(brain is null
        ? "Beyin durumu alınamadı."
        : $"Beyin: {(brain.Online ? "çevrimiçi" : "çevrimdışı")}  model={brain.Model ?? "-"}  " +
          $"gpu={brain.GpuOwner ?? "boşta"}  bütçe={brain.BudgetUsed * 100:0}%");
    Console.WriteLine();

    var robots = await api.GetRobotsAsync() ?? [];

    // §7 robots has no current-task column, so it is read off the running tasks.
    var running = (await api.GetTasksAsync("running")).ToLookup(t => t.RobotId);
    Console.Write(Table.Render(
        ["ROBOT", "DURUM", "BATARYA", "GÖREV", "SON GÖRÜLME"],
        [.. robots.Select(r => new string?[]
        {
            r.Id,
            r.State,
            r.BatterySoc is { } soc ? $"{soc * 100:0}%" : null,
            running[r.Id].FirstOrDefault()?.Title,
            r.LastSeen?.ToLocalTime().ToString("dd.MM HH:mm"),
        })]));
    return 0;
}));

var taskList = new Command("list", "Görevleri listele");
taskList.Options.Add(stateOption);
taskList.SetAction(async (parse, _) => await WithApi(async api =>
{
    var tasks = await api.GetTasksAsync(parse.GetValue(stateOption));
    Console.Write(Table.Render(
        ["ID", "BAŞLIK", "TİP", "DURUM", "ÖNCELİK", "ROBOT"],
        [.. tasks.Select(t => new string?[]
        {
            t.Id.ToString(), t.Title, t.Kind, t.State, t.Priority.ToString("0.###"), t.RobotId,
        })]));
    return 0;
}));

var taskShow = new Command("show", "Görev detayını göster");
taskShow.Arguments.Add(taskIdArgument);
taskShow.SetAction(async (parse, _) => await WithApi(async api =>
{
    var task = await api.GetTaskAsync(parse.GetValue(taskIdArgument));
    if (task is null)
    {
        Console.Error.WriteLine("Görev bulunamadı.");
        return 1;
    }

    Console.WriteLine($"{task.Id}  {task.Title}");
    Console.WriteLine($"tip={task.Kind}  durum={task.State}  öncelik={task.Priority:0.###}  " +
                      $"robot={task.RobotId ?? "-"}  kaynak={task.Source}");
    Console.WriteLine();
    Console.WriteLine("spec:");
    Console.WriteLine(JsonSerializer.Serialize(task.Spec, new JsonSerializerOptions { WriteIndented = true }));
    return 0;
}));

var taskCancel = new Command("cancel", "Görevi iptal et");
taskCancel.Arguments.Add(taskIdArgument);
taskCancel.SetAction(async (parse, _) => await WithApi(async api =>
{
    using var response = await api.CancelTaskAsync(parse.GetValue(taskIdArgument));
    return Report(response, "Görev iptal edildi.");
}));

var task = new Command("task", "Görev işlemleri");
task.Subcommands.Add(taskList);
task.Subcommands.Add(taskShow);
task.Subcommands.Add(taskCancel);

var approvalList = new Command("list", "Bekleyen onayları listele");
approvalList.SetAction(async (_, _) => await WithApi(async api =>
{
    var approvals = await api.GetPendingApprovalsAsync() ?? [];
    Console.Write(Table.Render(
        ["ID", "SEVİYE", "KONU", "KİMLİK", "SON TARİH"],
        [.. approvals.Select(a => new string?[]
        {
            a.Id.ToString(),
            a.Level.ToString(),
            a.SubjectKind,
            a.SubjectId,
            a.ExpiresAt.ToLocalTime().ToString("dd.MM HH:mm"),
        })]));
    return 0;
}));

var approvalShow = new Command("show", "Onay detayını göster");
approvalShow.Arguments.Add(approvalIdArgument);
approvalShow.SetAction(async (parse, _) => await WithApi(async api =>
{
    var approval = await api.GetApprovalAsync(parse.GetValue(approvalIdArgument));
    if (approval is null)
    {
        Console.Error.WriteLine("Onay bulunamadı.");
        return 1;
    }

    Console.WriteLine($"{approval.Id}  seviye {approval.Level}  {approval.SubjectKind}:{approval.SubjectId}");
    Console.WriteLine($"son tarih={approval.ExpiresAt.ToLocalTime():dd.MM.yyyy HH:mm}  karar={approval.Decision ?? "bekliyor"}");
    if (approval.PreviewUrl is { Length: > 0 })
    {
        Console.WriteLine($"önizleme: {approval.PreviewUrl}");
    }

    // §7 approvals.payload is free-form lab JSON (summary + cost/time estimates), so it is
    // printed whole rather than guessed at field by field.
    Console.WriteLine();
    Console.WriteLine("payload:");
    Console.WriteLine(JsonSerializer.Serialize(approval.Payload, new JsonSerializerOptions { WriteIndented = true }));
    return 0;
}));

var approvalApprove = new Command("approve", "Onayla");
approvalApprove.Arguments.Add(approvalIdArgument);
approvalApprove.Options.Add(noteOption);
approvalApprove.Options.Add(confirmOption);
approvalApprove.SetAction(async (parse, _) => await WithApi(async api =>
{
    var id = parse.GetValue(approvalIdArgument);
    var approval = await api.GetApprovalAsync(id);
    var confirmation = parse.GetValue(confirmOption);

    // §5.2 level 4 gate. The server enforces it too; this only stops an obvious mistake early.
    if (approval?.Level == 4 && !Level4.IsConfirmed(confirmation))
    {
        Console.Error.WriteLine($"Seviye 4 onayı için --confirm {Level4.Phrase} gerekli.");
        return 2;
    }

    using var response = await api.DecideAsync(id, approve: true, new ApprovalDecision(parse.GetValue(noteOption), confirmation));
    return Report(response, "Onaylandı.");
}));

var approvalReject = new Command("reject", "Reddet");
approvalReject.Arguments.Add(approvalIdArgument);
approvalReject.Options.Add(noteOption);
approvalReject.SetAction(async (parse, _) => await WithApi(async api =>
{
    using var response = await api.DecideAsync(
        parse.GetValue(approvalIdArgument),
        approve: false,
        new ApprovalDecision(parse.GetValue(noteOption), null));
    return Report(response, "Reddedildi.");
}));

var approval = new Command("approval", "Onay işlemleri");
approval.Subcommands.Add(approvalList);
approval.Subcommands.Add(approvalShow);
approval.Subcommands.Add(approvalApprove);
approval.Subcommands.Add(approvalReject);

var root = new RootCommand("NEML uzak API konsol aracı");
root.Subcommands.Add(login);
root.Subcommands.Add(logout);
root.Subcommands.Add(status);
root.Subcommands.Add(task);
root.Subcommands.Add(approval);

var campaign = new Command("campaign", "Eğitim kampanyaları");
var campaignList = new Command("list", "Kampanyaları listele");
campaignList.SetAction(async (_, _) => await PrintApiJson("api/v1/campaigns"));
var campaignShow = new Command("show", "Kampanya ve nesillerini göster");
var campaignId = new Argument<Guid>("id");
campaignShow.Arguments.Add(campaignId);
campaignShow.SetAction(async (parse, _) => await WithApi(async api =>
{
    var id = parse.GetValue(campaignId);
    PrintJson(await api.GetJsonAsync($"api/v1/campaigns/{id}"));
    PrintJson(await api.GetJsonAsync($"api/v1/campaigns/{id}/generations"));
    return 0;
}));
var campaignStop = new Command("stop", "Kampanya durdurma isteğini kuyruğa al");
var stopId = new Argument<Guid>("id");
campaignStop.Arguments.Add(stopId);
campaignStop.SetAction(async (parse, _) => await WithApi(async api =>
{
    using var response = await api.SendJsonAsync($"api/v1/campaigns/{parse.GetValue(stopId)}/stop", new { });
    return Report(response, "Durdurma isteği kuyruğa alındı.");
}));
campaign.Subcommands.Add(campaignList);
campaign.Subcommands.Add(campaignShow);
campaign.Subcommands.Add(campaignStop);
root.Subcommands.Add(campaign);

var skill = new Command("skill", "Skill kütüphanesi");
var skillList = new Command("list", "Güncel skill sürümlerini listele");
skillList.SetAction(async (_, _) => await PrintApiJson("api/v1/skills"));
var skillVersions = new Command("versions", "Bir skill'in sürümlerini göster");
var skillKey = new Argument<string>("key");
skillVersions.Arguments.Add(skillKey);
skillVersions.SetAction(async (parse, _) => await PrintApiJson(
    $"api/v1/skills/{Uri.EscapeDataString(parse.GetValue(skillKey)!)}/versions"));
skill.Subcommands.Add(skillList);
skill.Subcommands.Add(skillVersions);
root.Subcommands.Add(skill);

var genome = new Command("genome", "Genome soy ağacı");
var genomeTree = new Command("tree", "Soy ağacını göster");
genomeTree.SetAction(async (_, _) => await PrintApiJson("api/v1/genomes/tree"));
genome.Subcommands.Add(genomeTree);
root.Subcommands.Add(genome);

var printJob = new Command("print-job", "Baskı işleri");
var printList = new Command("list", "Baskı işlerini listele");
printList.SetAction(async (_, _) => await PrintApiJson("api/v1/print-jobs"));
var printCancel = new Command("cancel", "Baskı iptal isteğini kuyruğa al");
var printId = new Argument<Guid>("id");
printCancel.Arguments.Add(printId);
printCancel.SetAction(async (parse, _) => await WithApi(async api =>
{
    using var response = await api.SendJsonAsync(
        $"api/v1/print-jobs/{parse.GetValue(printId)}/cancel", new { reason = "CLI operator request" });
    return Report(response, "Baskı iptal isteği kuyruğa alındı.");
}));
printJob.Subcommands.Add(printList);
printJob.Subcommands.Add(printCancel);
root.Subcommands.Add(printJob);

var brain = new Command("brain", "Beyin komutları");
var brainCommand = new Command("command", "Doğal dil komutunu kuyruğa al");
var commandText = new Argument<string>("text");
brainCommand.Arguments.Add(commandText);
brainCommand.SetAction(async (parse, _) => await WithApi(async api =>
{
    using var response = await api.SendJsonAsync("api/v1/brain/command", new { text = parse.GetValue(commandText) });
    return Report(response, "Komut kuyruğa alındı.");
}));
var brainCommandStatus = new Command("show", "Komut durumunu göster");
var commandId = new Argument<Guid>("id");
brainCommandStatus.Arguments.Add(commandId);
brainCommandStatus.SetAction(async (parse, _) => await PrintApiJson(
    $"api/v1/brain/command/{parse.GetValue(commandId)}"));
brain.Subcommands.Add(brainCommand);
brain.Subcommands.Add(brainCommandStatus);
root.Subcommands.Add(brain);

return await root.Parse(args).InvokeAsync();

static Task<int> PrintApiJson(string path) => WithApi(async api =>
{
    PrintJson(await api.GetJsonAsync(path));
    return 0;
});

static void PrintJson(JsonElement? value) => Console.WriteLine(value is null
    ? "Veri yok."
    : JsonSerializer.Serialize(value.Value, new JsonSerializerOptions { WriteIndented = true }));

static async Task<int> WithApi(Func<CliApi, Task<int>> action)
{
    var session = Session.Load();
    if (session is null)
    {
        Console.Error.WriteLine("Oturum yok. Önce: nemlctl login --email <e-posta>");
        return 2;
    }

    using var api = new CliApi(session);
    try
    {
        return await action(api);
    }
    catch (HttpRequestException ex)
    {
        Console.Error.WriteLine($"API hatası: {ex.Message}");
        return 1;
    }
}

static int Report(HttpResponseMessage response, string success)
{
    if (response.IsSuccessStatusCode)
    {
        Console.WriteLine(success);
        return 0;
    }

    Console.Error.WriteLine($"Başarısız: HTTP {(int)response.StatusCode}");
    return 1;
}

static string Prompt()
{
    Console.Error.Write("Şifre: ");

    // ReadKey throws when stdin is a pipe, which is exactly how a script would feed it.
    if (Console.IsInputRedirected)
    {
        Console.Error.WriteLine();
        return Console.ReadLine() ?? string.Empty;
    }

    var builder = new StringBuilder();
    while (true)
    {
        var key = Console.ReadKey(intercept: true);
        if (key.Key == ConsoleKey.Enter)
        {
            Console.Error.WriteLine();
            return builder.ToString();
        }

        if (key.Key == ConsoleKey.Backspace)
        {
            if (builder.Length > 0)
            {
                builder.Length--;
            }
        }
        else if (!char.IsControl(key.KeyChar))
        {
            builder.Append(key.KeyChar);
        }
    }
}
