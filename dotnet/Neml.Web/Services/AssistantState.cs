// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
using System.Net;
using System.Text.Json;
using System.Text.RegularExpressions;
using Neml.Web.Layout;

namespace Neml.Web.Services;

/// <summary>
/// The floating assistant's memory: the conversation survives page changes, and each page tells it what
/// the operator is looking at so a question like "make this leg longer" needs no explanation.
/// </summary>
public sealed partial class AssistantState(ApiClient api)
{
    public sealed class Turn(string text, string mode)
    {
        public string Text { get; } = text;
        public string Mode { get; } = mode;
        public string? Reply { get; set; }
        public string? DraftId { get; set; }
        public string? DraftModel { get; set; }
        public bool Applied { get; set; }
        public DateTime Started { get; } = DateTime.UtcNow;
    }

    /// <summary>"screen" talks about what is open; "new_model" is the guided new-robot conversation.</summary>
    public string Mode { get; set; } = "screen";
    public bool Open { get; set; }
    public string? GenomeId { get; private set; }
    public string? ModelName { get; private set; }
    public string? Tab { get; private set; }
    public string? PickedPart { get; set; }
    public List<Turn> Turns { get; } = [];
    public bool Busy => Turns.Any(t => t.Reply is null);

    public event Action? Changed;

    public void SetModel(string? genomeId, string? modelName, string? tab)
    {
        GenomeId = genomeId;
        ModelName = modelName;
        Tab = tab;
        if (genomeId is null)
        {
            PickedPart = null;
        }

        Changed?.Invoke();
    }

    public void Notify() => Changed?.Invoke();

    public string Screen(string route) =>
        GenomeId is null
            ? $"page /{route}"
            : $"model page of '{ModelName}', tab '{Tab}', design {GenomeId}" + (PickedPart is null ? "" : $", selected part: {PickedPart}");

    [GeneratedRegex("bu ekran|ekranda ne|ne yapabilirim|nasıl kullan|yardım|bu sayfa", RegexOptions.IgnoreCase)]
    private static partial Regex HelpWords();

    public async Task SendAsync(string text, string route)
    {
        var turn = new Turn(text.Trim(), Mode);
        Turns.Add(turn);
        Changed?.Invoke();
        if (Mode == "screen" && text.Length < 80 && HelpWords().IsMatch(text))
        {
            turn.Reply = AssistantHelp.For(route, ModelName);
            Changed?.Invoke();
            return;
        }

        try
        {
            CommandAccepted? accepted;
            if (Mode == "new_model")
            {
                var history = Turns.Where(t => t.Mode == "new_model" && t != turn && t.Reply is not null)
                    .SelectMany(t => new object[] { new { role = "user", text = t.Text }, new { role = "assistant", text = t.Reply! } })
                    .ToList();
                accepted = await api.DesignModelAsync(turn.Text, history);
            }
            else if (GenomeId is not null)
            {
                accepted = await api.ChatModelAsync(GenomeId, turn.Text, Screen(route));
            }
            else
            {
                accepted = await api.SendBrainCommandAsync(turn.Text);
            }

            for (var i = 0; i < 450 && turn.Reply is null; i++)
            {
                await Task.Delay(2000);
                var status = await api.GetCommandAsync(accepted!.CommandId);
                if (status is null || status.State is "pending" or "delivered")
                {
                    continue;
                }

                Finish(turn, status);
            }

            turn.Reply ??= "Lab 15 dakikada cevap vermedi; meşgul ya da kapalı olabilir. Birazdan tekrar dene.";
        }
        catch (HttpRequestException ex)
        {
            turn.Reply = ex.StatusCode switch
            {
                HttpStatusCode.Unauthorized => "Oturumun sona ermiş; çıkış yapıp yeniden giriş yap.",
                HttpStatusCode.TooManyRequests => "Çok hızlı gönderdin (dakikada 10 komut sınırı); biraz bekleyip tekrar dene.",
                HttpStatusCode.Forbidden => "Bu işlem için yetkin yok.",
                null => "Sunucuya ulaşılamadı; bağlantını kontrol et.",
                _ => $"Mesaj gönderilemedi (hata {(int)ex.StatusCode}).",
            };
        }
        finally
        {
            Changed?.Invoke();
        }
    }

    private void Finish(Turn turn, CommandResult status)
    {
        var result = status.Result;
        if (status.State != "applied")
        {
            turn.Reply = "Yapamadım: " + (Field(result, "error") ?? status.State);
            return;
        }

        turn.Reply = turn.Mode == "screen" && GenomeId is null
            ? AskBrain.SayAbout(status.State, result)
            : Field(result, "reply") ?? "Tamam.";
        if (result is { ValueKind: JsonValueKind.Object } r && r.TryGetProperty("draft", out var draft) && draft.ValueKind == JsonValueKind.Object)
        {
            turn.DraftId = draft.GetProperty("id").GetString();
            turn.DraftModel = draft.TryGetProperty("model", out var m) ? m.GetString() : ModelName;
        }
    }

    public async Task ApplyAsync(Turn turn)
    {
        try
        {
            (await api.ApplyModelAsync(turn.DraftId!)).EnsureSuccessStatusCode();
            turn.Applied = true;
            turn.Reply += " Onay istedim: Onaylar ekranında seviye 4 onayını ver, tasarım aktif olur.";
        }
        catch (HttpRequestException)
        {
            turn.Reply += " (Onay istenemedi, tekrar dene.)";
        }

        Changed?.Invoke();
    }

    private static string? Field(JsonElement? element, string name) =>
        element is { ValueKind: JsonValueKind.Object } e && e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString()
            : null;
}

/// <summary>What each screen is for, in the operator's words. Answered on the spot, without the language model.</summary>
public static class AssistantHelp
{
    public static string For(string route, string? model)
    {
        var first = route.Split('/', '?')[0];
        var inModel = route.Contains('/');
        return first switch
        {
            "" => "Panel: robotların durumu, çalışan görevler ve bekleyen onaylar tek bakışta. Üst menüden Görevler, Modeller, Onaylar gibi ekranlara geçersin.",
            "gorevler" => "Görevler: üstteki kutuya serbest cümleyle yaz (örn. \"labirentte koştur\", \"durum nedir\"); beyin görev açar ya da soruyu cevaplar. Aşağıda görev listesi var, birine tıklayınca ayrıntısı açılır.",
            "beyin" => "Beyin: beynin sağlığı, kullandığı model, bütçe kullanımı ve komut geçmişi.",
            "evrim" when inModel =>
                $"'{model}' model sayfası: 3B tasarım (parçaya tıkla, boyutunu ve yerini düzenle, patlat, STL/STEP indir), Kartlar, İç aksam/malzeme, Simülasyon, Evrim ve eğitim. Bana \"bacak uzunluğunu 130 yap\" ya da \"kamerayı 10 mm öne al\" yazarak da değiştirtebilirsin. Değişiklikler önce taslak olur; beğenirsen Uygula ile onay istersin.",
            "evrim" => "Modeller: her robot modeli bir kart. Birini aç: 3B tasarım, kartlar, iç aksam, simülasyon ve evrim sekmeleri. Yeni bir model için bu pencerede \"Yeni model tasarla\"yı seç.",
            "onaylar" => "Onaylar: seviye 4 tasarım ve üretim onayları burada bekler. Onay yalnızca senindir; asistan senin yerine onaylamaz.",
            "genom" => "Genom ağacı: tasarım sürümleri ve hangisinin hangisinden türediği.",
            "yetenekler" => "Skill: robotun öğrendiği yetenekler ve doğrulama sonuçları.",
            "uretim" => "Üretim: baskı işleri ve kalite kontrol durumu.",
            "loglar" => "Loglar: sistemin kayıtları (kim ne zaman ne yaptı).",
            "ayarlar" => "Ayarlar: hesabın, model ve bildirim ayarların.",
            "bot" => "Bot: dışarıdan komut gönderen botlar ve erişim bilgileri.",
            _ => "Bu ekran için özel bir yardım yok; ne yapmak istediğini yaz, birlikte bakalım.",
        };
    }
}
