/* Bar Manager — réglages d'affichage et navigation */
(function () {
  'use strict';
  var KEY = 'bar:settings';
  var root = document.documentElement;
  var DEFAULTS = { theme: 'auto', accent: 'ambre', title: '1', font: '1', radius: 'soft', density: 'comfort', collapsed: false };

  function load() {
    try { return Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem(KEY) || '{}')); }
    catch (e) { return Object.assign({}, DEFAULTS); }
  }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }

  var state = load();
  var mq = matchMedia('(prefers-color-scheme: dark)');

  function apply() {
    var theme = state.theme === 'auto' ? (mq.matches ? 'dark' : 'light') : state.theme;
    root.setAttribute('data-bs-theme', theme);
    root.setAttribute('data-accent', state.accent);
    root.setAttribute('data-radius', state.radius);
    root.setAttribute('data-density', state.density);
    root.style.setProperty('--title-scale', state.title);
    root.style.setProperty('--font-scale', state.font);
    if (state.collapsed) root.setAttribute('data-sidebar', 'collapsed'); else root.removeAttribute('data-sidebar');
    sync();
  }

  /* Met à jour l'état visuel des contrôles du panneau */
  function sync() {
    document.querySelectorAll('[data-setting]').forEach(function (group) {
      var k = group.getAttribute('data-setting');
      group.querySelectorAll('button').forEach(function (b) {
        b.classList.toggle('on', b.getAttribute('data-value') === String(state[k]));
      });
    });
    var t = document.getElementById('titleRange'), f = document.getElementById('fontRange');
    if (t) { t.value = state.title; document.getElementById('titleOut').textContent = Math.round(state.title * 100) + '%'; }
    if (f) { f.value = state.font;  document.getElementById('fontOut').textContent  = Math.round(state.font * 100) + '%'; }
  }

  function set(key, value) { state[key] = value; save(); apply(); }

  /* Toast réutilisable : BarUI.toast('Vente enregistrée') */
  function toast(msg, ms) {
    var zone = document.getElementById('toastZone');
    if (!zone) return;
    var el = document.createElement('div');
    el.className = 'toast-bar';
    el.textContent = msg;
    zone.appendChild(el);
    setTimeout(function () { el.remove(); }, ms || 2600);
  }
  window.BarUI = { toast: toast, set: set, state: function () { return state; } };

  document.addEventListener('DOMContentLoaded', function () {
    apply();

    // Groupes de boutons (thème, accent, arrondi, densité)
    document.querySelectorAll('[data-setting] button').forEach(function (b) {
      b.addEventListener('click', function () {
        set(b.parentElement.getAttribute('data-setting'), b.getAttribute('data-value'));
      });
    });

    // Curseurs
    var t = document.getElementById('titleRange'), f = document.getElementById('fontRange');
    if (t) t.addEventListener('input', function () { set('title', t.value); });
    if (f) f.addEventListener('input', function () { set('font', f.value); });

    // Bouton soleil / lune
    var themeBtn = document.getElementById('themeBtn');
    if (themeBtn) themeBtn.addEventListener('click', function () {
      var current = root.getAttribute('data-bs-theme');
      set('theme', current === 'dark' ? 'light' : 'dark');
    });
    mq.addEventListener('change', function () { if (state.theme === 'auto') apply(); });

    // Réinitialiser
    var reset = document.getElementById('resetBtn');
    if (reset) reset.addEventListener('click', function () {
      state = Object.assign({}, DEFAULTS); save(); apply(); toast('Apparence réinitialisée');
    });

    // Menu : réduire (bureau) / ouvrir (mobile)
    var collapse = document.getElementById('collapseBtn');
    if (collapse) collapse.addEventListener('click', function () { set('collapsed', !state.collapsed); });
    var openMenu = function (open) { document.body.classList.toggle('menu-open', open); };
    var menuBtn = document.getElementById('menuBtn'), scrim = document.getElementById('scrim');
    if (menuBtn) menuBtn.addEventListener('click', function () { openMenu(true); });
    if (scrim) scrim.addEventListener('click', function () { openMenu(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') openMenu(false); });

    // Lien actif (menu latéral + barre du bas)
    var path = location.pathname;
    document.querySelectorAll('.nav-item[href], .tab[href]').forEach(function (a) {
      var href = a.getAttribute('href');
      var on = href === '/' ? path === '/' : path.indexOf(href) === 0;
      if (on) a.classList.add('active');
    });
  });
})();