async function fetchCards(){
  const res = await fetch('/api/cards');
  const data = await res.json();
  if (!data.success) throw new Error(data.error || 'Failed');
  return data.cards || [];
}

function fmtThen(c){
  const a = c.thenStart ?? c.then_start ?? null;
  const b = c.thenEnd ?? c.then_end ?? null;
  if (a && b && a !== b) return `${a}–${b}`;
  if (a) return `${a}`;
  if (b) return `${b}`;
  return '—';
}

function getTags(c){
  const tags = c.tags || [];
  const linkType = c.linkType || c.link_type;
  const pills = [];
  if (linkType) pills.push({t:linkType, type:'type'});
  for (const t of tags.slice(0,8)) pills.push({t, type:'tag'});
  return pills;
}

function render(cards){
  const root = document.getElementById('cards');
  const status = document.getElementById('status');
  const tmpl = document.getElementById('cardTmpl');
  root.innerHTML = '';

  if (!cards.length){
    status.textContent = 'No cards yet. Run /api/run-import to generate.';
    return;
  }
  status.textContent = `${cards.length} cards`;

  for (const c of cards){
    const node = tmpl.content.cloneNode(true);

    node.querySelector('.card__claim').textContent = c.claim || c.claim_text || '';

    const pillsEl = node.querySelector('.pills');
    for (const p of getTags(c)){
      const span = document.createElement('span');
      span.className = p.type === 'type' ? 'pill pill--type' : 'pill';
      span.textContent = p.t;
      pillsEl.appendChild(span);
    }

    node.querySelector('.then').textContent = fmtThen(c);

    const issueTitle = c.issueTitle || c.issue_title || `Issue ${c.beehiiv_id || ''}`;
    const pub = c.publishDate || c.publish_date;
    node.querySelector('.issue').textContent = pub ? `${issueTitle} · ${pub.slice(0,10)}` : issueTitle;

    const ev = c.evidence || [];
    const summary = node.querySelector('.evidence__sum');
    summary.textContent = ev.length ? `Evidence (${ev.length})` : 'Evidence';
    const list = node.querySelector('.evidence__list');
    for (const e of ev.slice(0,4)){
      const li = document.createElement('li');
      li.textContent = (e && e.quote) ? e.quote : String(e);
      list.appendChild(li);
    }

    const link = node.querySelector('.issueLink');
    const url = c.issueUrl || c.issue_url || c.url;
    if (url) link.href = url; else link.style.display = 'none';

    root.appendChild(node);
  }
}

function applySearch(all, q){
  q = (q || '').trim().toLowerCase();
  if (!q) return all;
  return all.filter(c => {
    const claim = (c.claim || '').toLowerCase();
    const tags = (c.tags || []).join(' ').toLowerCase();
    const issue = (c.issueTitle || '').toLowerCase();
    return claim.includes(q) || tags.includes(q) || issue.includes(q);
  });
}

(async function init(){
  const status = document.getElementById('status');
  const input = document.getElementById('q');
  try{
    const all = await fetchCards();
    let current = all;
    render(current);

    let t = null;
    input.addEventListener('input', () => {
      if (t) clearTimeout(t);
      t = setTimeout(() => {
        current = applySearch(all, input.value);
        render(current);
      }, 120);
    });
  }catch(e){
    status.textContent = `Error: ${e.message}`;
  }
})();
