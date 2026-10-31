// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using FirebaseAdmin;
using FirebaseAdmin.Messaging;
using Microsoft.EntityFrameworkCore;
using Neml.Domain.Enums;
using Neml.Infrastructure.Persistence;

namespace Neml.Api.Services;

/// <summary>Trigger table of NEML_SPEC.md 10.4.</summary>
public enum PushTrigger
{
    /// <summary>Approval requested for deployment level 3-4 — high priority, with sound.</summary>
    ApprovalRequested,

    /// <summary>Robot went to fault or estop — high priority, with sound.</summary>
    RobotFault,

    /// <summary>Task failed on its third attempt — normal priority, silent.</summary>
    TaskFailed,

    /// <summary>Campaign completed — normal priority, silent.</summary>
    CampaignCompleted,

    /// <summary>Print finished — low priority, silent.</summary>
    PrintFinished,

    /// <summary>Daily budget reached 90% — normal priority, silent.</summary>
    BudgetWarning,
}

/// <summary>FCM delivery for the spec 10.4 triggers. A missing credentials file disables it.</summary>
public sealed class PushNotifier
{
    private const int FcmBatchSize = 500;

    // Spec 10.4. FCM knows only High and Normal, so the "low" row is sent as Normal, silent.
    private static readonly Dictionary<PushTrigger, (Priority Priority, bool Sound)> Rules = new()
    {
        [PushTrigger.ApprovalRequested] = (Priority.High, true),
        [PushTrigger.RobotFault] = (Priority.High, true),
        [PushTrigger.TaskFailed] = (Priority.Normal, false),
        [PushTrigger.CampaignCompleted] = (Priority.Normal, false),
        [PushTrigger.PrintFinished] = (Priority.Normal, false),
        [PushTrigger.BudgetWarning] = (Priority.Normal, false),
    };

    private readonly IServiceScopeFactory _scopes;
    private readonly ILogger<PushNotifier> _log;
    private readonly bool _enabled;

    public PushNotifier(IServiceScopeFactory scopes, IConfiguration configuration, ILogger<PushNotifier> log)
    {
        _scopes = scopes;
        _log = log;

        var credentialsPath = configuration["Fcm:CredentialsPath"];
        if (string.IsNullOrWhiteSpace(credentialsPath) || !File.Exists(credentialsPath))
        {
            _log.LogWarning("FCM credentials not found at {Path}; push notifications are disabled.", credentialsPath);
            return;
        }

        // Handing the path to Application Default Credentials avoids GoogleCredential.FromFile,
        // which the Google auth library has deprecated.
        Environment.SetEnvironmentVariable("GOOGLE_APPLICATION_CREDENTIALS", credentialsPath);
        if (FirebaseApp.DefaultInstance is null)
        {
            FirebaseApp.Create();
        }

        _enabled = true;
    }

    public async Task NotifyAsync(PushTrigger trigger, string title, string body, CancellationToken ct = default)
    {
        if (!_enabled)
        {
            return;
        }

        var (priority, sound) = Rules[trigger];

        using var scope = _scopes.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<NemlDbContext>();
        var tokens = await db.Devices.AsNoTracking()
            .Where(d => d.PushToken != null && d.Platform != DevicePlatform.Web)
            .Select(d => d.PushToken!)
            .ToListAsync(ct);

        for (var offset = 0; offset < tokens.Count; offset += FcmBatchSize)
        {
            var batch = tokens.GetRange(offset, Math.Min(FcmBatchSize, tokens.Count - offset));
            var message = new MulticastMessage
            {
                // FirebaseAdmin 3.x renamed Tokens to Fids; devices.push_token goes here.
                Fids = batch,
                Notification = new Notification { Title = title, Body = body },
                Data = new Dictionary<string, string> { ["trigger"] = trigger.ToString() },
                Android = new AndroidConfig
                {
                    Priority = priority,
                    Notification = new AndroidNotification
                    {
                        ChannelId = sound ? "neml_critical" : "neml_default",
                        Sound = sound ? "default" : null,
                    },
                },
                Apns = new ApnsConfig
                {
                    Aps = new Aps { Sound = sound ? "default" : null, ContentAvailable = !sound },
                },
            };

            try
            {
                var result = await FirebaseMessaging.DefaultInstance.SendEachForMulticastAsync(message, ct);
                if (result.FailureCount > 0)
                {
                    _log.LogWarning("Push {Trigger}: {Failed}/{Total} deliveries failed.",
                        trigger, result.FailureCount, batch.Count);
                }
            }
            catch (FirebaseMessagingException ex)
            {
                _log.LogError(ex, "Push {Trigger} could not be delivered.", trigger);
            }
        }
    }
}
