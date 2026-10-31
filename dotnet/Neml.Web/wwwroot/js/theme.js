// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
// The chosen theme (light / dark) is applied before the first paint; with no choice the system setting decides.
(function () {
    try {
        var saved = localStorage.getItem('neml-theme');
        if (saved === 'light' || saved === 'dark') { document.documentElement.dataset.theme = saved; }
    } catch (e) { /* storage blocked: follow the system */ }
})();
window.nemlTheme = {
    choice: function () { return document.documentElement.dataset.theme || 'auto'; },
    set: function (value) {
        if (value === 'auto') {
            delete document.documentElement.dataset.theme;
            try { localStorage.removeItem('neml-theme'); } catch (e) { /* ignore */ }
        } else {
            document.documentElement.dataset.theme = value;
            try { localStorage.setItem('neml-theme', value); } catch (e) { /* ignore */ }
        }
        return value;
    },
    effective: function () {
        return document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
    },
};
