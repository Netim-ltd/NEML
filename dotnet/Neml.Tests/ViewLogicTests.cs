// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Neml.Web;

namespace Neml.Tests;

/// <summary>Screens 7 and 11-12: the pure logic behind the pages.</summary>
public sealed class ViewLogicTests
{
    private static AuditEntry Entry(string actor, string action, string? outcome = "ok", string? target = null) =>
        new(1, DateTimeOffset.UnixEpoch, actor, action, target, outcome, null);

    [Fact]
    public void Polyline_scales_into_the_box_and_survives_flat_and_empty_series()
    {
        Assert.Equal("0,10 5,0 10,5", ViewLogic.Polyline([0, 2, 1], 10, 10).Replace("5,5", "5,5"));
        Assert.Equal("", ViewLogic.Polyline([], 10, 10));
        Assert.DoesNotContain("NaN", ViewLogic.Polyline([3, 3, 3], 10, 10));
        Assert.Equal("0,10", ViewLogic.Polyline([7], 10, 10));
    }

    [Fact]
    public void Audit_tabs_and_filter_match_the_mobile_screen()
    {
        var all = new[]
        {
            Entry("user:mg", "approve"),
            Entry("agent:mechanical", "cad.export", target: "bracket"),
            Entry("agent:mechanical", "cad.generate", "error"),
        };

        Assert.Equal(3, ViewLogic.FilterAudit(all, "audit", "").Count());
        Assert.Equal(2, ViewLogic.FilterAudit(all, "tools", "").Count());
        Assert.Single(ViewLogic.FilterAudit(all, "errors", ""));
        Assert.Equal("cad.export", ViewLogic.FilterAudit(all, "audit", " BRACKET ").Single().Action);
        Assert.Empty(ViewLogic.FilterAudit(all, "audit", "zzz"));
    }

    [Theory]
    [InlineData(10.0, 10.3, true)]
    [InlineData(10.0, 10.31, false)]
    public void Dimension_tolerance_is_0_3_mm(double nominal, double measured, bool ok) =>
        Assert.Equal(ok, ViewLogic.DimOk(measured, nominal));

    [Fact]
    public void Mass_warp_and_number_parsing()
    {
        Assert.True(ViewLogic.MassOk(104, 100));
        Assert.False(ViewLogic.MassOk(106, 100));
        Assert.Null(ViewLogic.MassOk(1, 0));
        Assert.True(ViewLogic.WarpOk(0.5));
        Assert.False(ViewLogic.WarpOk(0.51));
        Assert.Equal(1.5, ViewLogic.Number("1,5"));
        Assert.Null(ViewLogic.Number("abc"));
        Assert.Null(ViewLogic.Number("NaN"));
    }

    [Fact]
    public void Qc_form_uses_the_keys_the_lab_handler_reads()
    {
        var wire = new QcForm(1, 2, 3, 1, 2, 3, 50, 50, 0.1, true, false).ToWire();
        foreach (var key in new[] { "dim_1_mm", "dim_3_nominal_mm", "mass_g", "mass_nominal_g", "warp_mm", "hole_gauge_ok", "layer_adhesion_ok" })
        {
            Assert.True(wire.ContainsKey(key), key);
        }
    }
}
