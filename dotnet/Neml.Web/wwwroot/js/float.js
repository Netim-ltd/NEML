// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
// The floating assistant window: drag it by its header, resize it from the corner, and it
// reopens where it was left. Storage may be blocked, so every access is guarded.
window.neml = window.neml || {};

window.neml.popOut = (url) => {
    window.open(url, 'neml-assistant', 'popup=yes,width=460,height=760');
};

window.neml.scrollEnd = (el) => {
    if (el) el.scrollTop = el.scrollHeight;
};

window.neml.floatWindow = (win, handle) => {
    if (!win || !handle) return;
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem('neml.assistant') || 'null'); } catch { /* blocked */ }
    const place = (left, top) => {
        const maxLeft = Math.max(0, window.innerWidth - 80);
        const maxTop = Math.max(0, window.innerHeight - 60);
        win.style.left = Math.min(Math.max(0, left), maxLeft) + 'px';
        win.style.top = Math.min(Math.max(0, top), maxTop) + 'px';
        win.style.right = 'auto';
        win.style.bottom = 'auto';
    };
    if (saved) {
        place(saved.left, saved.top);
        if (saved.width) win.style.width = saved.width + 'px';
        if (saved.height) win.style.height = saved.height + 'px';
    }
    const store = () => {
        const r = win.getBoundingClientRect();
        try { localStorage.setItem('neml.assistant', JSON.stringify({ left: r.left, top: r.top, width: r.width, height: r.height })); } catch { /* blocked */ }
    };
    let drag = null;
    handle.addEventListener('pointerdown', (e) => {
        if (e.target.closest('button')) return;
        const r = win.getBoundingClientRect();
        drag = { dx: e.clientX - r.left, dy: e.clientY - r.top };
        handle.setPointerCapture(e.pointerId);
    });
    handle.addEventListener('pointermove', (e) => {
        if (drag) place(e.clientX - drag.dx, e.clientY - drag.dy);
    });
    handle.addEventListener('pointerup', () => { if (drag) { drag = null; store(); } });
    new ResizeObserver(store).observe(win);
};
