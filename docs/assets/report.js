// JUP-Eval research page: measure tabs (arrow keys move between them), chart tooltips, the page index, and the copy buttons.
(function () {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches ||
    document.documentElement.classList.contains('motion-off');
  const transition = { duration: 260, easing: 'cubic-bezier(.2,.7,.2,1)' };
  const panelFor = tab => document.getElementById(tab.getAttribute('aria-controls'));

  // Preserve each system's position as the new measure reorders the chart.
  const chartPositions = panel => new Map([...panel.querySelectorAll('li[data-tip]')].map(row => {
    const bar = row.querySelector('.col i');
    return [row.dataset.tip, { row: row.getBoundingClientRect(), bar: bar.getBoundingClientRect() }];
  }));

  const show = tab => {
    if (tab.getAttribute('aria-selected') === 'true') return;
    const current = tabs.find(t => t.getAttribute('aria-selected') === 'true');
    const previous = reduceMotion() ? null : chartPositions(panelFor(current));
    tip.classList.remove('on');
    cur = null;
    for (const t of tabs) {
      const on = t === tab;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
    }
    if (!previous) return;
    const panel = panelFor(tab);
    const horizontal = matchMedia('(max-width: 760px)').matches;
    const rows = [...panel.querySelectorAll('li[data-tip]')];
    // A rapid switch can return to a panel that is still animating.
    panel.getAnimations({ subtree: true }).filter(animation => animation.id === 'rank-change')
      .forEach(animation => animation.cancel());
    const next = chartPositions(panel);
    for (const row of rows) {
      const from = previous.get(row.dataset.tip), to = next.get(row.dataset.tip);
      if (!from) continue;
      const dx = from.row.left - to.row.left, dy = from.row.top - to.row.top;
      row.animate([{ transform: `translate(${dx}px,${dy}px)` }, { transform: 'none' }],
        { ...transition, id: 'rank-change' });
      const scale = horizontal ? from.bar.width / to.bar.width : from.bar.height / to.bar.height;
      if (Number.isFinite(scale)) {
        row.querySelector('.col i').animate(
          [{ scale: horizontal ? `${scale} 1` : `1 ${scale}` }, { scale: '1' }],
          { ...transition, id: 'rank-change' });
      }
    }
  };
  tabs.forEach((tab, i) => {
    tab.addEventListener('click', () => show(tab));
    tab.addEventListener('keydown', e => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (e.key === 'Home' || e.key === 'End' || step) {
        e.preventDefault();
        const next = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : (i + step + tabs.length) % tabs.length;
        tabs[next].focus(); show(tabs[next]);
      }
    });
  });

  // Animate the contents so the summary and the user's scroll position stay anchored.
  for (const details of document.querySelectorAll('details')) {
    const summary = details.querySelector('summary');
    const content = details.querySelector('.disclosure-body');
    let motion;
    summary.addEventListener('click', event => {
      if (!content || event.defaultPrevented || !content.animate) return;
      const opening = motion ? details.dataset.motion === 'closing' : !details.open;
      event.preventDefault();
      const settle = () => {
        details.open = details.dataset.motion === 'opening';
        content.inert = false;
        delete details.dataset.motion;
        summary.removeAttribute('aria-expanded');
        motion = null;
      };
      details.dataset.motion = opening ? 'opening' : 'closing';
      summary.setAttribute('aria-expanded', String(opening));
      if (reduceMotion()) {
        if (motion) motion.cancel();
        settle();
        return;
      }
      content.inert = !opening;
      if (motion) {
        motion.reverse();
        return;
      }
      details.open = true;
      const height = content.getBoundingClientRect().height;
      const duration = Math.min(400, 210 + height * .25);
      motion = content.animate([
        { height:'0px', opacity:.4 },
        { height:height + 'px', opacity:1 }
      ], { duration, easing:'cubic-bezier(.35,0,.22,1)', id:'disclosure' });
      if (!opening) {
        motion.currentTime = duration;
        motion.reverse();
      }
      motion.onfinish = settle;
    });
  }

  // One tooltip for every chart mark. Values are also printed on the marks and in the tables, so hover only adds detail.
  const tip = document.createElement('div');
  tip.className = 'tip'; tip.setAttribute('aria-hidden', 'true');
  const tName = document.createElement('strong'), tSub = document.createElement('span');
  tip.append(tName, tSub); document.body.append(tip);
  let cur = null;
  document.addEventListener('pointermove', e => {
    if (e.pointerType === 'touch') return;
    const mark = e.target.closest('[data-tip]');
    if (mark === cur) return;
    cur = mark;
    if (!mark) { tip.classList.remove('on'); return; }
    tName.textContent = mark.dataset.tip;
    tSub.textContent = mark.dataset.sub || '';
    const anchor = mark.querySelector('.col i, .dot') || mark;
    const rect = anchor.getBoundingClientRect();
    const box = tip.getBoundingClientRect();
    const x = Math.min(innerWidth - box.width - 8, Math.max(8, rect.left + rect.width / 2 - box.width / 2));
    const above = rect.top - box.height - 8;
    const y = above >= 8 ? above : Math.min(innerHeight - box.height - 8, Math.max(8, rect.bottom + 8));
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
    tip.classList.add('on');
  }, { passive:true });
  const hideTip = () => {
    if (cur) { tip.classList.remove('on'); cur = null; }
  };
  document.addEventListener('scroll', hideTip, { passive: true });
  document.documentElement.addEventListener('pointerleave', hideTip);

  // "On this page": mark the section being read.
  const links = [...document.querySelectorAll('.toc a')];
  const secs = links.map(a => document.querySelector(a.getAttribute('href'))).filter(Boolean);
  if ('IntersectionObserver' in window && secs.length) {
    const io = new IntersectionObserver(es => {
      for (const e of es) if (e.isIntersecting) {
        for (const a of links) a.setAttribute('aria-current', a.getAttribute('href') === '#' + e.target.id ? 'true' : 'false');
      }
    }, { rootMargin: '-20% 0px -70% 0px' });
    secs.forEach(s => io.observe(s));
  }
  const share = document.querySelector('[data-share]');
  const shareLabel = share.querySelector('[data-share-label]');
  const shareStatus = document.querySelector('.share-status');
  const reportURL = document.querySelector('meta[property="og:url"]').content;
  let resetShare;
  share.addEventListener('click', async () => {
    clearTimeout(resetShare);
    try {
      await navigator.clipboard.writeText(reportURL);
      share.classList.add('is-done');
      shareLabel.textContent = 'Link copied';
      shareStatus.textContent = '';
      resetShare = setTimeout(() => {
        share.classList.remove('is-done');
        shareLabel.textContent = 'Copy link';
      }, 2000);
    } catch {
      shareStatus.textContent = 'Copy this link: ' + reportURL;
    }
  });

  for (const b of document.querySelectorAll('[data-copy]')) {
    b.addEventListener('click', async () => {
      const text = document.getElementById(b.dataset.copy).innerText;
      try { await navigator.clipboard.writeText(text); b.textContent = 'Copied'; }
      catch (e) { b.textContent = 'Select the text to copy'; }
      setTimeout(() => { b.textContent = 'Copy citation'; }, 2000);
    });
  }
})();
