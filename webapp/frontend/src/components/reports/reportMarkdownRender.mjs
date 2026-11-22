function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function decorateInline(escaped) {
  return String(escaped)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`\[([A-Z_]+)\]`/g, '<span class="erw-badge erw-badge-$1">[$1]</span>')
    .replace(/`([A-Z_]+)`/g, '<span class="erw-badge erw-badge-$1">$1</span>')
    .replace(/_([^_]+)_/g, '<em>$1</em>');
}

/** Bare "Created:" / "Top blockers by fan-out:" lines from older stored reports. */
function isLegacyGroupLabel(line) {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith('-') || trimmed.startsWith('#') || trimmed.startsWith('|')) {
    return false;
  }
  if (trimmed.startsWith('**') || trimmed.startsWith('>')) return false;
  return /^.+:\s*$/.test(trimmed) || /^(Created|Resolved|Status transitions|Top blockers by fan-out)\s*$/i.test(trimmed);
}

function bulletDepth(line) {
  const match = line.match(/^(\s*)- /);
  if (!match) return -1;
  return Math.floor(match[1].length / 2) + 1;
}

/**
 * Escape then format modern health-report markdown (KPI table, badges, AI insights).
 * Supports nested bullets and legacy bare group labels without jagged FACTS indent.
 */
export function renderMarkdown(md) {
  const lines = String(md || '').split('\n');
  const html = [];
  let listDepth = 0;
  let openLiDepth = 0;
  let nestUnderGroup = false;
  let inTable = false;
  let inInsight = false;
  let heroOpen = false;
  let sectionOpen = false;

  const closeOpenLi = () => {
    if (openLiDepth > 0) {
      html.push('</li>');
      openLiDepth = 0;
    }
  };

  const closeLists = (toDepth = 0) => {
    while (listDepth > toDepth) {
      closeOpenLi();
      html.push('</ul>');
      listDepth -= 1;
      if (listDepth > 0) {
        html.push('</li>');
        openLiDepth = 0;
      }
    }
  };

  const closeTable = () => {
    if (inTable) {
      html.push('</tbody></table></div>');
      inTable = false;
    }
  };

  const closeInsight = () => {
    if (inInsight) {
      html.push('</div>');
      inInsight = false;
    }
  };

  const closeHero = () => {
    if (heroOpen) {
      html.push('</div>');
      heroOpen = false;
    }
  };

  const closeSection = () => {
    if (sectionOpen) {
      html.push('</section>');
      sectionOpen = false;
    }
  };

  const pushBullet = (depth, contentHtml, extraClass = '') => {
    if (depth < listDepth) {
      closeLists(depth);
    }
    while (listDepth < depth) {
      html.push(listDepth === 0 ? '<ul class="erw-fact-list">' : '<ul class="erw-fact-list-nested">');
      listDepth += 1;
      openLiDepth = 0;
    }
    if (openLiDepth === depth) {
      html.push('</li>');
    }
    const cls = extraClass ? ` class="${extraClass}"` : '';
    html.push(`<li${cls}>${contentHtml}`);
    openLiDepth = depth;
  };

  for (const raw of lines) {
    const line = raw;
    if (line.startsWith('|') && line.includes('|')) {
      closeLists();
      closeInsight();
      const cells = line
        .replace(/^\|/, '')
        .replace(/\|$/, '')
        .split('|')
        .map((c) => c.trim());
      if (cells.every((c) => /^:?-+:?$/.test(c))) {
        continue;
      }
      if (!inTable) {
        html.push('<div class="erw-kpi-wrap"><table class="erw-kpi-table"><thead><tr>');
        cells.forEach((c) => html.push(`<th>${escapeHtml(c)}</th>`));
        html.push('</tr></thead><tbody>');
        inTable = true;
      } else {
        html.push('<tr>');
        cells.forEach((c) => html.push(`<td>${decorateInline(escapeHtml(c))}</td>`));
        html.push('</tr>');
      }
      continue;
    }
    closeTable();

    if (line.startsWith('# ')) {
      closeLists();
      closeInsight();
      closeSection();
      closeHero();
      html.push('<div class="erw-report-hero"><div class="erw-report-kicker">Daily Project Health</div>');
      html.push(`<h1>${escapeHtml(line.slice(2))}</h1>`);
      heroOpen = true;
    } else if (line.startsWith('## ') && /^\d+\./.test(line.slice(3).trim())) {
      closeLists();
      closeInsight();
      closeHero();
      closeSection();
      const title = line.slice(3).trim();
      const match = title.match(/^(\d+)\.\s*(.*)$/);
      const num = match?.[1] || '';
      const rest = match?.[2] || title;
      html.push(
        `<section class="erw-report-section"><div class="erw-section-head">` +
          `<span class="erw-section-num">${escapeHtml(num)}</span>` +
          `<h2>${escapeHtml(rest)}</h2></div>`,
      );
      sectionOpen = true;
    } else if (line.startsWith('## ')) {
      closeLists();
      closeInsight();
      html.push(`<h2 class="erw-report-subtitle">${escapeHtml(line.slice(3))}</h2>`);
    } else if (line.startsWith('### AI Insight')) {
      closeLists();
      closeInsight();
      html.push('<div class="erw-ai-insight"><div class="erw-ai-label">AI Insight</div>');
      inInsight = true;
    } else if (line.startsWith('### ')) {
      closeLists();
      closeInsight();
      const heading = line.slice(4).trim();
      const factsLike = /^Facts/i.test(heading);
      html.push(`<h3 class="${factsLike ? 'erw-facts-heading' : ''}">${escapeHtml(heading)}</h3>`);
    } else if (line.startsWith('> ')) {
      closeLists();
      const inner = decorateInline(escapeHtml(line.slice(2)));
      if (inInsight) {
        html.push(`<p>${inner}</p>`);
      } else {
        html.push(`<p class="erw-report-meta"><em>${inner}</em></p>`);
        closeHero();
      }
    } else if (/^\s*- /.test(line)) {
      closeInsight();
      let depth = bulletDepth(line);
      const content = line.replace(/^\s*- /, '');
      const isGroup = /^\*\*[^*]+\*\*$/.test(content.trim());
      if (nestUnderGroup && depth === 1 && !isGroup) {
        depth = 2;
      }
      if (isGroup) nestUnderGroup = true;
      else if (depth <= 1) nestUnderGroup = false;
      pushBullet(depth, decorateInline(escapeHtml(content)), isGroup ? 'erw-fact-group' : '');
    } else if (isLegacyGroupLabel(line)) {
      closeInsight();
      const label = line.trim().replace(/:$/, '');
      pushBullet(
        Math.max(listDepth, 1),
        `<span class="erw-fact-group-label">${decorateInline(escapeHtml(label))}</span>`,
        'erw-fact-group',
      );
      nestUnderGroup = true;
    } else if (line.trim() === '---') {
      closeLists();
      closeInsight();
      closeHero();
      html.push('<hr class="erw-report-rule" />');
    } else if (!line.trim()) {
      closeInsight();
    } else {
      closeLists();
      const inner = decorateInline(escapeHtml(line));
      if (inInsight) {
        html.push(`<p>${inner}</p>`);
      } else {
        html.push(`<p class="erw-report-para">${inner}</p>`);
      }
    }
  }
  closeLists();
  closeTable();
  closeInsight();
  closeHero();
  closeSection();
  return html.join('\n');
}
