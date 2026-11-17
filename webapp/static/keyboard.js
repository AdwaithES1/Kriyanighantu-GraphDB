// On-screen Devanagari keyboard. It types into the text field that was focused last.
// Usage: Keyboard.mount(containerElement)  -> the container gets the keys; show or hide it yourself.
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

  function edit(change) {
    if (!target || !target.isConnected) return;
    const start = target.selectionStart ?? target.value.length, end = target.selectionEnd ?? start;
    const [value, caret] = change(target.value, start, end);
    target.value = value;
    target.focus();
    target.setSelectionRange(caret, caret);
    target.dispatchEvent(new Event('input', { bubbles: true }));
  }
  const insert = text => edit((v, s, e) => [v.slice(0, s) + text + v.slice(e), s + text.length]);
  const backspace = () => edit((v, s, e) => s === e ? [v.slice(0, Math.max(0, s - 1)) + v.slice(e), Math.max(0, s - 1)] : [v.slice(0, s) + v.slice(e), s]);

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
        for (const char of row) line.append(button(char, () => insert(char)));
        container.append(line);
      }
    }
    const actions = document.createElement('div');
    actions.className = 'keys';
    actions.append(button('Space', () => insert(' '), true), button('⌫ Delete', backspace, true));
    container.append(actions);
  }
  return { mount };
})();
