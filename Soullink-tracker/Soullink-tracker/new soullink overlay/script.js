/* ===========================================================
   SOUL-LINK OVERLAY · HOLY-STYLE · SCRIPT
   =========================================================== */

(() => {
const $ = (id) => document.getElementById(id);
const overlay = $('overlay');
const panel = $('settings-panel');

/* ---------- Settings-Panel ---------- */
$('settings-toggle').addEventListener('click', () => panel.classList.toggle('open'));
$('settings-close').addEventListener('click', () => panel.classList.remove('open'));

/* ---------- Scale Overlay an Fenstergröße ---------- */
function fitScale() {
    const sx = window.innerWidth / 1920;
    const sy = window.innerHeight / 1080;
    const scale = Math.min(sx, sy, 1);
    overlay.style.setProperty('--scale', scale);
    overlay.style.transform = `scale(${scale})`;
}
window.addEventListener('resize', fitScale);
fitScale();

/* ---------- Bindings: einfach text-input -> display ---------- */
const bindText = (inputId, displayId) => {
    const inp = $(inputId), out = $(displayId);
    if (!inp || !out) return;
    inp.addEventListener('input', () => { out.textContent = inp.value || out.dataset.placeholder || ''; });
};
bindText('logo-text', 'logo-display');
bindText('run-label', 'run-label-display');
bindText('run-value', 'run-value-display');
bindText('cap-label', 'cap-label-display');
bindText('cap-value', 'cap-value-display');
bindText('best-label', 'best-label-display');
bindText('best-value', 'best-value-display');

$('player1-name').addEventListener('input', e => {
    $('player1-display').textContent = e.target.value || 'SPIELER 1';
});
$('player2-name').addEventListener('input', e => {
    $('player2-display').textContent = e.target.value || 'SPIELER 2';
});

/* ---------- Sichtbarkeit ---------- */
const bindShow = (cbId, el) => {
    $(cbId).addEventListener('change', e => {
        const node = typeof el === 'string' ? $(el) : el;
        node.classList.toggle('hidden', !e.target.checked);
    });
};
bindShow('show-header', 'header-bar');
bindShow('show-names', 'player1-tag');
$('show-names').addEventListener('change', e => $('player2-tag').classList.toggle('hidden', !e.target.checked));
bindShow('show-team', 'team-grid');
bindShow('show-cam1', 'cam1');
bindShow('show-cam2', 'cam2');
bindShow('show-chat', 'chat');

$('team-bg').addEventListener('change', e => {
    $('team-grid').classList.toggle('no-bg', !e.target.checked);
});

$('hide-labels').addEventListener('change', e => {
    document.body.classList.toggle('hide-labels', e.target.checked);
});

/* ---------- Chat-Transparenz ---------- */
$('chat-opacity').addEventListener('input', e => {
    const v = e.target.value;
    $('chat-opacity-val').textContent = v + '%';
    document.documentElement.style.setProperty('--chat-opacity', v / 100);
});

/* ---------- Farben ---------- */
const cssVar = (id, varName) => $(id).addEventListener('input', e => {
    document.documentElement.style.setProperty(varName, e.target.value);
});
cssVar('accent1', '--accent1');
cssVar('accent2', '--accent2');
cssVar('frame-color', '--frame');
cssVar('header-bg', '--header-bg');
cssVar('logo-color', '--logo-color');
cssVar('bg-color', '--bg-color');

/* ---------- Fonts ---------- */
$('font-display').addEventListener('change', e => document.documentElement.style.setProperty('--font-display', e.target.value));
$('font-body').addEventListener('change', e => document.documentElement.style.setProperty('--font-body', e.target.value));

/* ---------- Hintergrund-Bild ---------- */
const bgLayer = $('bg-layer');
$('bg-upload').addEventListener('change', e => {
    const f = e.target.files[0]; if (!f) return;
    const r = new FileReader();
    r.onload = ev => {
        bgLayer.style.backgroundImage = `url(${ev.target.result})`;
        bgLayer.classList.add('show-bg');
    };
    r.readAsDataURL(f);
});
$('bg-clear').addEventListener('click', () => {
    bgLayer.style.backgroundImage = '';
    bgLayer.classList.remove('show-bg');
    $('bg-upload').value = '';
});
$('bg-bright').addEventListener('input', e => {
    $('bg-bright-val').textContent = e.target.value + '%';
    document.documentElement.style.setProperty('--bg-bright', e.target.value + '%');
});
$('export-with-bg').addEventListener('change', e => {
    bgLayer.classList.toggle('show-bg', e.target.checked || !!bgLayer.style.backgroundImage);
});

/* ---------- Logo-Bild ---------- */
const logoCircle = $('logo-circle');
$('logo-upload').addEventListener('change', e => {
    const f = e.target.files[0]; if (!f) return;
    const r = new FileReader();
    r.onload = ev => {
        logoCircle.style.backgroundImage = `url(${ev.target.result})`;
        logoCircle.classList.add('has-image');
    };
    r.readAsDataURL(f);
});
$('logo-clear').addEventListener('click', () => {
    logoCircle.style.backgroundImage = '';
    logoCircle.classList.remove('has-image');
    $('logo-upload').value = '';
});

/* ---------- Team-Grid rendern ---------- */
function renderTeamGrid() {
    const n = parseInt($('pair-count').value, 10);
    const c1 = $('team-col-1'), c2 = $('team-col-2');
    c1.innerHTML = ''; c2.innerHTML = '';
    for (let i = 1; i <= n; i++) {
        c1.insertAdjacentHTML('beforeend', `<div class="slot" data-slot="L${i}"><span class="slot-placeholder">P1·${i}</span></div>`);
        c2.insertAdjacentHTML('beforeend', `<div class="slot" data-slot="R${i}"><span class="slot-placeholder">P2·${i}</span></div>`);
    }
    attachSlotHandlers();
}
$('pair-count').addEventListener('change', renderTeamGrid);
renderTeamGrid();

/* ---------- Slot-Upload (Klick im Edit-Mode) ---------- */
let currentSlot = null;
const slotUpload = $('slot-upload');
function attachSlotHandlers() {
    document.querySelectorAll('.slot').forEach(s => {
        s.addEventListener('click', () => {
            if (!document.body.classList.contains('edit-mode')) return;
            if (s.querySelector('img')) {
                // Bild vorhanden → leeren
                s.innerHTML = `<span class="slot-placeholder">${s.dataset.slot}</span>`;
                return;
            }
            currentSlot = s;
            slotUpload.click();
        });
    });
}
slotUpload.addEventListener('change', e => {
    const f = e.target.files[0]; if (!f || !currentSlot) return;
    const r = new FileReader();
    r.onload = ev => {
        currentSlot.innerHTML = `<img src="${ev.target.result}" alt="">`;
    };
    r.readAsDataURL(f);
    slotUpload.value = '';
});

/* ---------- Edit-Mode + Drag/Resize ---------- */
$('edit-mode-toggle').addEventListener('change', e => {
    document.body.classList.toggle('edit-mode', e.target.checked);
});

let drag = null;
overlay.addEventListener('mousedown', e => {
    if (!document.body.classList.contains('edit-mode')) return;
    const target = e.target.closest('[data-draggable]');
    if (!target) return;
    if (e.target.classList.contains('slot') || e.target.closest('.slot')) return;

    const rect = target.getBoundingClientRect();
    const scale = parseFloat(overlay.style.transform.match(/scale\(([\d.]+)\)/)?.[1] || 1);
    const isResize = (e.offsetX > target.offsetWidth - 20) && (e.offsetY > target.offsetHeight - 20);

    drag = {
        target, isResize, scale,
        startX: e.clientX, startY: e.clientY,
        startW: target.offsetWidth, startH: target.offsetHeight,
        startLeft: target.offsetLeft, startTop: target.offsetTop,
        shift: e.shiftKey,
        ratio: target.offsetWidth / target.offsetHeight
    };
    // Falls noch nicht positioniert: aktuelle Position fixieren
    if (!target.style.left) {
        target.style.left = target.offsetLeft + 'px';
        target.style.top = target.offsetTop + 'px';
        target.style.right = 'auto';
        target.style.bottom = 'auto';
        target.style.transform = '';
    }
    e.preventDefault();
});
window.addEventListener('mousemove', e => {
    if (!drag) return;
    const dx = (e.clientX - drag.startX) / drag.scale;
    const dy = (e.clientY - drag.startY) / drag.scale;
    if (drag.isResize) {
        let w = Math.max(60, drag.startW + dx);
        let h = Math.max(40, drag.startH + dy);
        if (e.shiftKey) h = w / drag.ratio;
        drag.target.style.width = w + 'px';
        drag.target.style.height = h + 'px';
    } else {
        drag.target.style.left = (drag.startLeft + dx) + 'px';
        drag.target.style.top = (drag.startTop + dy) + 'px';
    }
});
window.addEventListener('mouseup', () => drag = null);

/* ---------- Reset Layout ---------- */
$('reset-layout').addEventListener('click', () => {
    document.querySelectorAll('[data-draggable]').forEach(el => {
        el.style.cssText = '';
    });
});

/* ---------- PNG Export ---------- */
$('export-png').addEventListener('click', async () => {
    const withBg = $('export-with-bg').checked;
    const hadBg = bgLayer.classList.contains('show-bg');
    if (withBg && bgLayer.style.backgroundImage) bgLayer.classList.add('show-bg');
    if (!withBg) bgLayer.classList.remove('show-bg');

    // Temporär skalierung entfernen für 1:1 export
    const originalTransform = overlay.style.transform;
    overlay.style.transform = 'scale(1)';

    try {
        const dataUrl = await htmlToImage.toPng(overlay, {
            width: 1920,
            height: 1080,
            pixelRatio: 1,
            backgroundColor: withBg ? null : 'rgba(0,0,0,0)',
            cacheBust: true
        });
        const a = document.createElement('a');
        a.href = dataUrl;
        a.download = 'soullink-overlay.png';
        a.click();
    } catch (err) {
        alert('Export fehlgeschlagen: ' + err.message);
    } finally {
        overlay.style.transform = originalTransform;
        if (!hadBg && !withBg) bgLayer.classList.remove('show-bg');
        else if (hadBg) bgLayer.classList.add('show-bg');
    }
});

})();
