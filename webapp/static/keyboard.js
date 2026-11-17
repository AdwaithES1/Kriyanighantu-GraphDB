// On-screen Devanagari keyboard. It types into the text field that was focused last (if it is still visible),
// otherwise into a fallback field.
// Usage: const kb = Keyboard.attach(toggleButton, panel, fallback)
//          the button shows and hides the keys in `panel`; `fallback` is a field, or a function returning one.
//          kb.hide() closes it, e.g. after the form is submitted so the results are in view.
const Keyboard = (() => {
  const GROUPS = [
    ['स्वर', [['अ', 'आ', 'इ', 'ई', 'उ', 'ऊ', 'ऋ', 'ॠ', 'ऌ', 'ॡ'], ['ए', 'ऐ', 'ओ', 'औ', 'अं', 'अः', 'अँ', 'ॐ']]],
    ['व्यञ्जन', [['क', 'ख', 'ग', 'घ', 'ङ'], ['च', 'छ', 'ज', 'झ', 'ञ'], ['ट', 'ठ', 'ड', 'ढ', 'ण'], ['त', 'थ', 'द', 'ध', 'न'],
      ['प', 'फ', 'ब', 'भ', 'म'], ['य', 'र', 'ल', 'व', 'श', 'ष', 'स', 'ह'], ['क्ष', 'त्र', 'ज्ञ']]],
    ['मात्राएँ एवं चिह्न', [['ा', 'ि', 'ी', 'ु', 'ू', 'ृ', 'ॄ', 'ॢ', 'ॣ'], ['े', 'ै', 'ो', 'ौ', '्', '़', 'ं', 'ः', 'ँ', 'ऽ'],
      ['।', '॥', '०', '१', '२', '३', '४', '५', '६', '७', '८', '९']]],
  ];
  let target = null;
  document.addEventListener('focusin', event => {
    const el = event.target;
    if ((el.tagName === 'INPUT' && el.type === 'text') || el.tagName === 'TEXTAREA') target = el;
  });

  let fallbackOf = new Map();  // panel -> fallback, for the panel whose key was pressed
  const visible = el => el && el.isConnected && el.getClientRects().length > 0;
  const resolve = fallback => (typeof fallback === 'function' ? fallback() : fallback);
  function field(panel) {
    return visible(target) ? target : resolve(fallbackOf.get(panel)) || null;
  }

  function edit(panel, change) {
    const input = field(panel);
    if (!input) return;
    const start = input.selectionStart ?? input.value.length, end = input.selectionEnd ?? start;
    const [value, caret] = change(input.value, start, end);
    input.value = value;
    input.focus();
    input.setSelectionRange(caret, caret);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }
  const insert = (panel, text) => edit(panel, (v, s, e) => [v.slice(0, s) + text + v.slice(e), s + text.length]);
  const backspace = panel => edit(panel, (v, s, e) => s === e ? [v.slice(0, Math.max(0, s - 1)) + v.slice(e), Math.max(0, s - 1)] : [v.slice(0, s) + v.slice(e), s]);

  function button(label, onClick, wide) {
    const key = document.createElement('button');
    key.type = 'button';
    key.className = 'key' + (wide ? ' wide' : '');
    key.textContent = label;
    key.addEventListener('mousedown', event => event.preventDefault());  // keep the text field focused
    key.addEventListener('click', onClick);
    return key;
  }

  function mount(container) {
    container.classList.add('keyboard');
    for (const [label, rows] of GROUPS) {
      const heading = document.createElement('h4');
      heading.textContent = label;
      container.append(heading);
      for (const row of rows) {
        const line = document.createElement('div');
        line.className = 'keys';
        for (const char of row) line.append(button(char, () => insert(container, char)));
        container.append(line);
      }
    }
    const actions = document.createElement('div');
    actions.className = 'keys';
    actions.append(button('Space', () => insert(container, ' '), true), button('⌫ Delete', () => backspace(container), true));
    container.append(actions);
  }

  function attach(toggle, panel, fallback) {
    mount(panel);
    fallbackOf.set(panel, fallback);
    const set = show => {
      panel.hidden = !show;
      toggle.setAttribute('aria-expanded', String(show));
    };
    toggle.addEventListener('click', () => {
      set(panel.hidden);
      if (!panel.hidden) { const input = field(panel); if (input) input.focus(); }
    });
    set(false);
    return { hide: () => set(false) };
  }
  return { mount, attach };
})();
