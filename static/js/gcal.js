/* ─────────────────────────────────────────────────────────
 * Google Calendar clone engine for the SOMTool outreach view.
 *
 * Consumes window.__GCAL_DATA__ = { items, events, palette,
 * today, urls } that outreach_schedule.html embeds and renders
 * four views (Month / Week / Day / Schedule) + mini-month +
 * calendar list + popover + keyboard shortcuts. State lives in
 * localStorage so refresh preserves view / cursor / hidden
 * calendars.
 * ────────────────────────────────────────────────────────── */

(function () {
  "use strict";

  const data = window.__GCAL_DATA__ || {
    items: [], events: [], palette: {}, today: null, urls: {},
  };

  const DOW_FULL = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
  const DOW = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
  const DOW_SHORT = ["S","M","T","W","T","F","S"];
  const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  const STORE_KEY = "gcal.state.v2";
  const HOUR_PX = 48;
  const VIEW_LABELS = { day: "Day", week: "Week", month: "Month", agenda: "Schedule" };

  const state = loadState();
  const items = data.items.map(parseItem).sort((a, b) => a.start - b.start);
  const eventsById = Object.fromEntries(data.events.map((e) => [e.id, e]));
  const allItemsByKey = indexItemsByDate(items);

  const $shell = document.querySelector(".gcal-shell");
  if (!$shell) return;
  const $canvas = $shell.querySelector(".gcal-canvas");
  const $range = $shell.querySelector(".gcal-range");
  const $mini = $shell.querySelector(".gcal-mini");
  const $calListEvents = $shell.querySelector(".gcal-cal-list-events");
  const $calListStatus = $shell.querySelector(".gcal-cal-list-status");
  const $searchWrap = $shell.querySelector(".gcal-search");
  const $searchInput = $searchWrap && $searchWrap.querySelector("input");
  const $searchBtn = $searchWrap && $searchWrap.querySelector(".search-icon-btn");
  const $viewWrap = $shell.querySelector(".gcal-view");
  const $viewBtn = $viewWrap && $viewWrap.querySelector(".gcal-view-btn");
  const $viewBtnLabel = $viewBtn && $viewBtn.querySelector(".view-label");
  const $viewMenu = $viewWrap && $viewWrap.querySelector(".gcal-view-menu");
  const $popover = document.getElementById("gcal-popover");

  const urls = data.urls || {};
  let selectedChipId = null;

  wireTopbar();
  wireSidebar();
  wireKeyboard();
  wirePopoverDismiss();
  renderCalendarList();
  render();

  setInterval(() => {
    if (state.view === "week" || state.view === "day") positionNowLine();
  }, 60000);

  // ── State ────────────────────────────────────────────
  function loadState() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (raw) {
        const s = JSON.parse(raw);
        return {
          view: s.view || "week",
          cursor: s.cursor || data.today,
          hiddenEvents: Array.isArray(s.hiddenEvents) ? s.hiddenEvents : [],
          hiddenStatuses: Array.isArray(s.hiddenStatuses) ? s.hiddenStatuses : [],
          collapsedSections: Array.isArray(s.collapsedSections) ? s.collapsedSections : [],
          search: "",
        };
      }
    } catch (e) { /* ignore */ }
    return {
      view: "week", cursor: data.today, hiddenEvents: [], hiddenStatuses: [],
      collapsedSections: [], search: "",
    };
  }
  function saveState() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        view: state.view, cursor: state.cursor,
        hiddenEvents: state.hiddenEvents, hiddenStatuses: state.hiddenStatuses,
        collapsedSections: state.collapsedSections,
      }));
    } catch (e) { /* ignore */ }
  }

  function parseItem(raw) {
    const start = new Date(raw.scheduled_at);
    const end = new Date(start.getTime() + 30 * 60 * 1000);
    return {
      ...raw, start, end,
      dateKey: dateKey(start),
      minutes: start.getHours() * 60 + start.getMinutes(),
      durationMin: 30,
    };
  }
  function indexItemsByDate(xs) {
    const m = {};
    xs.forEach((x) => { (m[x.dateKey] = m[x.dateKey] || []).push(x); });
    return m;
  }

  // ── Date helpers ─────────────────────────────────────
  function parseISODate(s) {
    if (!s) return new Date();
    const [y, m, d] = s.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  function dateKey(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  function cursorDate() { return parseISODate(state.cursor); }
  function todayDate() { return parseISODate(data.today || dateKey(new Date())); }
  function sameDay(a, b) {
    return a.getFullYear() === b.getFullYear()
      && a.getMonth() === b.getMonth()
      && a.getDate() === b.getDate();
  }
  function addDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
  function startOfWeek(d) { const x = new Date(d); x.setDate(x.getDate() - x.getDay()); return x; }
  function fmtTime(d) {
    let h = d.getHours();
    const m = d.getMinutes();
    const ampm = h >= 12 ? "pm" : "am";
    h = h % 12 || 12;
    return m === 0 ? `${h}${ampm}` : `${h}:${String(m).padStart(2, "0")}${ampm}`;
  }
  function fmtHour(h) {
    if (h === 0) return "";
    const ampm = h >= 12 ? "PM" : "AM";
    const hh = h % 12 || 12;
    return `${hh} ${ampm}`;
  }
  function fmtTimezone() {
    const off = -new Date().getTimezoneOffset() / 60;
    const sign = off >= 0 ? "+" : "-";
    return `GMT${sign}${String(Math.abs(off)).padStart(2, "0")}`;
  }

  // ── Visibility filter ────────────────────────────────
  function visibleItems() {
    const q = (state.search || "").trim().toLowerCase();
    return items.filter((i) => {
      if (state.hiddenEvents.includes(i.event_id)) return false;
      if (state.hiddenStatuses.includes(i.status)) return false;
      if (!q) return true;
      const hay = `${i.contact_name} ${i.contact_email} ${i.event_name} ${i.action_type} ${i.preview}`.toLowerCase();
      return hay.includes(q);
    });
  }

  // ── Render root ──────────────────────────────────────
  function render() {
    renderRange();
    if ($viewBtnLabel) $viewBtnLabel.textContent = VIEW_LABELS[state.view] || "Week";
    renderMini();
    $canvas.innerHTML = "";
    if (state.view === "month") renderMonth();
    else if (state.view === "week") renderWeek(7);
    else if (state.view === "day") renderWeek(1);
    else renderAgenda();
    saveState();
  }

  function renderRange() {
    const c = cursorDate();
    if (state.view === "month") {
      $range.textContent = `${MONTHS[c.getMonth()]} ${c.getFullYear()}`;
    } else if (state.view === "week") {
      const s = startOfWeek(c);
      const e = addDays(s, 6);
      if (s.getMonth() === e.getMonth()) {
        $range.textContent = `${MONTHS[s.getMonth()]} ${c.getFullYear()}`;
      } else {
        $range.textContent = `${MONTHS[s.getMonth()].slice(0,3)} \u2013 ${MONTHS[e.getMonth()].slice(0,3)} ${e.getFullYear()}`;
      }
    } else if (state.view === "day") {
      $range.textContent = `${MONTHS[c.getMonth()]} ${c.getFullYear()}`;
    } else {
      $range.textContent = "Schedule";
    }
  }

  // ── Mini-month ───────────────────────────────────────
  function renderMini() {
    const c = cursorDate();
    const first = new Date(c.getFullYear(), c.getMonth(), 1);
    const gridStart = addDays(first, -first.getDay());
    let html = `<div class="gcal-mini-head">
      <div class="gcal-mini-title">${MONTHS[c.getMonth()]} ${c.getFullYear()}</div>
      <div class="gcal-mini-nav">
        <button type="button" aria-label="Previous month" data-mini="-1">${svgChev("left", 18)}</button>
        <button type="button" aria-label="Next month" data-mini="1">${svgChev("right", 18)}</button>
      </div>
    </div><div class="gcal-mini-grid">`;
    DOW_SHORT.forEach((d) => { html += `<div class="gcal-mini-dow">${d}</div>`; });
    const today = todayDate();
    for (let i = 0; i < 42; i++) {
      const d = addDays(gridStart, i);
      const classes = ["gcal-mini-day"];
      if (d.getMonth() !== c.getMonth()) classes.push("other");
      if (sameDay(d, today)) classes.push("today");
      if (sameDay(d, c) && !sameDay(d, today)) classes.push("selected");
      if (allItemsByKey[dateKey(d)]) classes.push("has-events");
      html += `<div class="${classes.join(" ")}" data-date="${dateKey(d)}">${d.getDate()}</div>`;
    }
    html += "</div>";
    $mini.innerHTML = html;

    $mini.querySelectorAll(".gcal-mini-day").forEach((el) => {
      el.addEventListener("click", () => {
        state.cursor = el.dataset.date;
        if (state.view === "agenda") state.view = "day";
        render();
      });
    });
    $mini.querySelectorAll("[data-mini]").forEach((b) => {
      b.addEventListener("click", () => {
        const c2 = cursorDate();
        c2.setMonth(c2.getMonth() + Number(b.dataset.mini));
        state.cursor = dateKey(c2);
        renderMini();
      });
    });
  }

  // ── Calendar list ────────────────────────────────────
  function sectionCollapsed(id) { return state.collapsedSections.includes(id); }
  function toggleSection(id) {
    const idx = state.collapsedSections.indexOf(id);
    if (idx >= 0) state.collapsedSections.splice(idx, 1);
    else state.collapsedSections.push(id);
    saveState();
    applySectionCollapse();
  }
  function applySectionCollapse() {
    $shell.querySelectorAll(".gcal-cal-section").forEach((sec) => {
      sec.classList.toggle("collapsed", sectionCollapsed(sec.dataset.section));
    });
  }

  function renderCalendarList() {
    if ($calListEvents) {
      $calListEvents.innerHTML = "";
      data.events.forEach((ev) => {
        const off = state.hiddenEvents.includes(ev.id);
        const li = document.createElement("li");
        li.className = "gcal-cal-item c-" + (ev.color || "peacock") + (off ? " off" : "");
        li.innerHTML = `
          <span class="swatch" aria-hidden="true"></span>
          <span class="gcal-cal-name" title="${escapeHtml(ev.name)}">${escapeHtml(ev.name)}</span>
          <span class="gcal-cal-count">${ev.count || 0}</span>`;
        li.addEventListener("click", () => {
          const idx = state.hiddenEvents.indexOf(ev.id);
          if (idx >= 0) state.hiddenEvents.splice(idx, 1);
          else state.hiddenEvents.push(ev.id);
          renderCalendarList(); render();
        });
        $calListEvents.appendChild(li);
      });
    }
    if ($calListStatus) {
      $calListStatus.innerHTML = "";
      [
        { id: "planned", label: "Planned", color: "graphite" },
        { id: "approved", label: "Approved", color: "basil" },
        { id: "sent", label: "Sent", color: "peacock" },
        { id: "skipped", label: "Skipped / failed", color: "tomato" },
      ].forEach((s) => {
        const ids = s.id === "skipped" ? ["skipped", "failed"] : [s.id];
        const off = ids.every((id) => state.hiddenStatuses.includes(id));
        const li = document.createElement("li");
        li.className = "gcal-cal-item c-" + s.color + (off ? " off" : "");
        li.innerHTML = `<span class="swatch" aria-hidden="true"></span><span class="gcal-cal-name">${s.label}</span>`;
        li.addEventListener("click", () => {
          const anyOn = ids.some((id) => !state.hiddenStatuses.includes(id));
          ids.forEach((id) => {
            const idx = state.hiddenStatuses.indexOf(id);
            if (anyOn && idx < 0) state.hiddenStatuses.push(id);
            if (!anyOn && idx >= 0) state.hiddenStatuses.splice(idx, 1);
          });
          renderCalendarList(); render();
        });
        $calListStatus.appendChild(li);
      });
    }
    applySectionCollapse();
  }

  // ── Month view ───────────────────────────────────────
  function renderMonth() {
    const c = cursorDate();
    const today = todayDate();
    const first = new Date(c.getFullYear(), c.getMonth(), 1);
    const gridStart = addDays(first, -first.getDay());
    const vis = visibleItems();
    const byKey = indexItemsByDate(vis);

    const wrap = el("div", "gcal-month");
    const dow = el("div", "gcal-month-dow");
    ["SUN","MON","TUE","WED","THU","FRI","SAT"].forEach((d) => {
      const cell = el("div"); cell.textContent = d; dow.appendChild(cell);
    });
    wrap.appendChild(dow);

    const grid = el("div", "gcal-month-grid");
    for (let i = 0; i < 42; i++) {
      const d = addDays(gridStart, i);
      const key = dateKey(d);
      const cell = el("div", "gcal-month-cell");
      if (d.getMonth() !== c.getMonth()) cell.classList.add("other-month");
      if (sameDay(d, today)) cell.classList.add("today");

      const num = el("div", "gcal-month-daynum");
      num.innerHTML = `<span class="num">${d.getDate()}</span>`;
      num.addEventListener("click", () => { state.cursor = key; state.view = "day"; render(); });
      cell.appendChild(num);

      const chips = el("div", "gcal-month-chips");
      const dayItems = (byKey[key] || []).slice().sort((a,b) => a.start - b.start);
      const MAX = 3;
      dayItems.slice(0, MAX).forEach((it) => chips.appendChild(monthChip(it)));
      if (dayItems.length > MAX) {
        const more = el("div", "gcal-month-more");
        more.textContent = `${dayItems.length - MAX} more`;
        more.addEventListener("click", () => { state.cursor = key; state.view = "day"; render(); });
        chips.appendChild(more);
      }
      cell.appendChild(chips);
      grid.appendChild(cell);
    }
    wrap.appendChild(grid);
    $canvas.appendChild(wrap);
  }

  function monthChip(it) {
    const chip = el("div", "gcal-chip " + (it.status || "planned") + " c-" + (it.color || "peacock"));
    if (selectedChipId === it.id) chip.classList.add("selected");
    chip.innerHTML = `
      <span class="chip-dot"></span>
      <span class="chip-time">${fmtTime(it.start)}</span>
      <span class="chip-title">${escapeHtml(chipTitle(it))}</span>`;
    chip.addEventListener("click", (e) => {
      e.stopPropagation();
      openPopover(it, chip);
    });
    return chip;
  }
  function chipTitle(it) {
    const action = humanAction(it.action_type);
    if (it.contact_name) return `${action}, ${it.contact_name}`;
    return action;
  }
  function humanAction(t) {
    switch (t) {
      case "email_initial": return "Intro email";
      case "email_followup": return "Follow-up email";
      case "email_survey": return "Survey email";
      case "call_invite": return "Invite call";
      case "call_followup": return "Follow-up call";
      default: return (t || "Action").replace(/_/g, " ");
    }
  }

  // ── Week / Day view ──────────────────────────────────
  function renderWeek(cols) {
    const c = cursorDate();
    const start = cols === 7 ? startOfWeek(c) : c;
    const days = [];
    for (let i = 0; i < cols; i++) days.push(addDays(start, i));
    const today = todayDate();
    const vis = visibleItems();

    const wrap = el("div", "gcal-week");
    wrap.style.setProperty("--cols", cols);

    const header = el("div", "gcal-week-header");
    const gmt = el("div", "gcal-week-gmt"); gmt.textContent = fmtTimezone();
    header.appendChild(gmt);
    days.forEach((d) => {
      const dh = el("div", "gcal-week-dayhead");
      if (sameDay(d, today)) dh.classList.add("today");
      dh.innerHTML = `<div class="dow">${DOW[d.getDay()].toUpperCase()}</div><div class="daynum">${d.getDate()}</div>`;
      dh.addEventListener("click", () => { state.cursor = dateKey(d); state.view = "day"; render(); });
      header.appendChild(dh);
    });
    wrap.appendChild(header);

    const allday = el("div", "gcal-week-allday");
    const alldayLabel = el("div", "gcal-week-allday-label"); alldayLabel.textContent = "";
    allday.appendChild(alldayLabel);
    days.forEach(() => allday.appendChild(el("div", "gcal-week-allday-cell")));
    wrap.appendChild(allday);

    const scroll = el("div", "gcal-week-scroll");
    const grid = el("div", "gcal-week-grid");

    const hours = el("div", "gcal-hour-labels");
    for (let h = 0; h < 24; h++) {
      hours.appendChild(el("div", "gcal-hour-label", fmtHour(h)));
    }
    grid.appendChild(hours);

    days.forEach((d) => {
      const col = el("div", "gcal-day-col");
      col.dataset.date = dateKey(d);
      for (let h = 0; h < 24; h++) col.appendChild(el("div", "gcal-hour-slot"));
      const dayItems = vis.filter((it) => sameDay(it.start, d));
      packBlocks(dayItems).forEach((b) => col.appendChild(renderBlock(b)));
      grid.appendChild(col);
    });

    scroll.appendChild(grid);
    wrap.appendChild(scroll);
    $canvas.appendChild(wrap);

    requestAnimationFrame(() => {
      const now = new Date();
      const hour = sameDay(now, c) ? Math.max(0, now.getHours() - 1) : 7;
      scroll.scrollTop = hour * HOUR_PX;
      positionNowLine();
    });
  }

  function packBlocks(dayItems) {
    const sorted = dayItems.slice().sort((a,b) => a.start - b.start);
    const columns = [];
    const blocks = sorted.map((it) => {
      const startMin = it.minutes;
      const endMin = startMin + it.durationMin;
      let colIdx = -1;
      for (let i = 0; i < columns.length; i++) {
        if (columns[i] <= startMin) { colIdx = i; break; }
      }
      if (colIdx < 0) { colIdx = columns.length; columns.push(endMin); }
      else columns[colIdx] = endMin;
      return { item: it, startMin, endMin, col: colIdx };
    });
    const colCount = Math.max(1, columns.length);
    blocks.forEach((b) => { b.colCount = colCount; });
    return blocks;
  }

  function renderBlock(b) {
    const it = b.item;
    const top = (b.startMin / 60) * HOUR_PX;
    const height = Math.max(22, ((b.endMin - b.startMin) / 60) * HOUR_PX - 2);
    const widthPct = 100 / b.colCount;
    const leftPct = b.col * widthPct;
    const blk = el("div", "gcal-block " + (it.status || "planned") + " c-" + (it.color || "peacock"));
    blk.style.top = top + "px";
    blk.style.height = height + "px";
    blk.style.left = `calc(${leftPct}% + 2px)`;
    blk.style.width = `calc(${widthPct}% - 4px)`;
    blk.innerHTML = `
      <div class="block-title">${escapeHtml(humanAction(it.action_type))}${it.contact_name ? ", " + escapeHtml(it.contact_name) : ""}</div>
      <div class="block-time">${fmtTime(it.start)}</div>`;
    blk.addEventListener("click", (e) => { e.stopPropagation(); openPopover(it, blk); });
    return blk;
  }

  function positionNowLine() {
    const wrap = $canvas.querySelector(".gcal-week");
    if (!wrap) return;
    wrap.querySelectorAll(".gcal-now-line").forEach((n) => n.remove());
    const now = new Date();
    const cols = wrap.querySelectorAll(".gcal-day-col");
    cols.forEach((col) => {
      const key = col.dataset.date;
      if (!key) return;
      const d = parseISODate(key);
      if (!sameDay(d, now)) return;
      const line = el("div", "gcal-now-line");
      line.style.top = ((now.getHours() + now.getMinutes() / 60) * HOUR_PX) + "px";
      col.appendChild(line);
    });
  }

  // ── Agenda view ──────────────────────────────────────
  function renderAgenda() {
    const vis = visibleItems();
    const wrap = el("div", "gcal-agenda");
    if (vis.length === 0) {
      const empty = el("div", "gcal-agenda-empty");
      empty.innerHTML = `<strong>No events scheduled</strong>Use the Create button to plan outreach for your events.`;
      wrap.appendChild(empty);
      $canvas.appendChild(wrap);
      return;
    }
    const byKey = indexItemsByDate(vis);
    const keys = Object.keys(byKey).sort();
    const today = todayDate();
    keys.forEach((k) => {
      const d = parseISODate(k);
      const group = el("div", "gcal-agenda-group");
      const datebox = el("div", "gcal-agenda-datebox");
      if (sameDay(d, today)) datebox.classList.add("today");
      datebox.innerHTML = `<div class="daynum">${d.getDate()}</div><div class="dayname">${DOW[d.getDay()].toUpperCase()}</div>`;
      group.appendChild(datebox);
      const list = el("div", "gcal-agenda-list");
      byKey[k].sort((a,b) => a.start - b.start).forEach((it) => list.appendChild(agendaRow(it)));
      group.appendChild(list);
      wrap.appendChild(group);
    });
    $canvas.appendChild(wrap);
  }
  function agendaRow(it) {
    const row = el("div", "gcal-agenda-row c-" + (it.color || "peacock"));
    row.innerHTML = `
      <div class="gcal-agenda-time">${fmtTime(it.start)}</div>
      <div class="gcal-agenda-dot"></div>
      <div class="gcal-agenda-title">
        <span>${escapeHtml(humanAction(it.action_type))}${it.contact_name ? ", " + escapeHtml(it.contact_name) : ""}</span>
        <span class="meta">${escapeHtml(it.event_name || "")}</span>
      </div>
      <div class="gcal-agenda-status ${it.status}">${it.status}</div>`;
    row.addEventListener("click", () => openPopover(it, row));
    return row;
  }

  // ── Popover ──────────────────────────────────────────
  function openPopover(it, anchor) {
    closePopover();
    selectedChipId = it.id;
    const color = "c-" + (it.color || "peacock");
    const ev = eventsById[it.event_id];
    const approveUrl = (urls.approve || "").replace("__id__", it.id);
    const skipUrl = (urls.skip || "").replace("__id__", it.id);
    const deleteUrl = (urls.del || "").replace("__id__", it.id);
    const eventUrl = ev && urls.event ? urls.event.replace("__id__", ev.id) : null;

    const dateLabel = `${DOW_FULL[it.start.getDay()]}, ${MONTHS[it.start.getMonth()]} ${it.start.getDate()}`;
    const timeLabel = `${fmtTime(it.start)} \u2013 ${fmtTime(it.end)}`;

    $popover.className = "gcal-popover open " + color;
    $popover.innerHTML = `
      <div class="gcal-pop-bar" aria-hidden="true"></div>
      <div class="gcal-pop-head">
        <div class="gcal-pop-swatch" aria-hidden="true"></div>
        <div class="gcal-pop-title">${escapeHtml(humanAction(it.action_type))}${it.contact_name ? ", " + escapeHtml(it.contact_name) : ""}</div>
        <button class="gcal-pop-close" type="button" aria-label="Close">${svgIcon("x", 18)}</button>
      </div>
      <div class="gcal-pop-meta">
        <div class="gcal-pop-meta-row">${svgIcon("clock", 20)}<span>${dateLabel} \u00b7 ${timeLabel}</span></div>
        ${ev ? `<div class="gcal-pop-meta-row">${svgIcon("calendar", 20)}<span>${eventUrl ? `<a href="${eventUrl}">${escapeHtml(ev.name)}</a>` : escapeHtml(ev.name)}</span></div>` : ""}
        ${it.contact_email ? `<div class="gcal-pop-meta-row">${svgIcon("user", 20)}<span><a href="mailto:${escapeHtml(it.contact_email)}">${escapeHtml(it.contact_email)}</a></span></div>` : ""}
        <div class="gcal-pop-meta-row">${svgIcon("status", 20)}<span class="gcal-agenda-status ${it.status}" style="margin:0;">${it.status}</span></div>
        ${it.html_link ? `<div class="gcal-pop-meta-row">${svgIcon("link", 20)}<span><a href="${escapeHtml(it.html_link)}" target="_blank" rel="noopener">Open in Google Calendar</a></span></div>` : ""}
        ${it.meet_url ? `<div class="gcal-pop-meta-row">${svgIcon("video", 20)}<span><a href="${escapeHtml(it.meet_url)}" target="_blank" rel="noopener">Join Google Meet</a></span></div>` : ""}
        ${it.synced ? `<div class="gcal-pop-meta-row" style="color:var(--gcal-text-muted);">${svgIcon("check", 20)}<span>Synced with Google Calendar</span></div>` : ""}
      </div>
      ${it.preview ? `<div class="gcal-pop-body">${escapeHtml(it.preview)}</div>` : ""}
      <div class="gcal-pop-actions">
        ${it.status !== "skipped" && it.status !== "failed" && it.status !== "sent" && skipUrl ? `<form method="post" action="${skipUrl}"><button class="gcal-btn" type="submit">Skip</button></form>` : ""}
        ${it.status === "planned" && approveUrl ? `<form method="post" action="${approveUrl}"><button class="gcal-btn primary" type="submit">Approve</button></form>` : ""}
        ${deleteUrl ? `<form method="post" action="${deleteUrl}" onsubmit="return confirm('Delete this action?');"><button class="gcal-btn danger" type="submit">Delete</button></form>` : ""}
      </div>`;

    $popover.querySelector(".gcal-pop-close").addEventListener("click", closePopover);

    // Reflect selection in month chips
    if (state.view === "month") {
      $canvas.querySelectorAll(".gcal-chip.selected").forEach((el) => el.classList.remove("selected"));
      anchor.classList.add("selected");
    }

    const a = anchor.getBoundingClientRect();
    const pw = 448, ph = Math.min(520, window.innerHeight - 32);
    let left = a.right + 12;
    if (left + pw > window.innerWidth - 16) left = Math.max(16, a.left - pw - 12);
    if (left < 16) left = Math.max(16, (window.innerWidth - pw) / 2);
    let top = a.top;
    if (top + ph > window.innerHeight - 16) top = Math.max(16, window.innerHeight - ph - 16);
    $popover.style.left = left + "px";
    $popover.style.top = top + "px";
  }
  function closePopover() {
    if (!$popover) return;
    if (selectedChipId) {
      $canvas.querySelectorAll(".gcal-chip.selected").forEach((el) => el.classList.remove("selected"));
      selectedChipId = null;
    }
    $popover.classList.remove("open");
    $popover.innerHTML = "";
  }
  function wirePopoverDismiss() {
    document.addEventListener("click", (e) => {
      if (!$popover.classList.contains("open")) return;
      if (!$popover.contains(e.target)) closePopover();
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePopover(); });
  }

  // ── Topbar / sidebar / shortcuts ─────────────────────
  function wireTopbar() {
    const todayBtn = $shell.querySelector(".gcal-today-btn");
    if (todayBtn) todayBtn.addEventListener("click", () => {
      state.cursor = data.today || dateKey(new Date());
      render();
    });
    const [prev, next] = $shell.querySelectorAll(".gcal-nav .gcal-icon-btn");
    if (prev) prev.addEventListener("click", () => step(-1));
    if (next) next.addEventListener("click", () => step(1));

    if ($searchBtn) {
      $searchBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        $searchWrap.classList.add("expanded");
        setTimeout(() => $searchInput && $searchInput.focus(), 0);
      });
    }
    if ($searchInput) {
      $searchInput.addEventListener("input", () => { state.search = $searchInput.value; render(); });
      $searchInput.addEventListener("blur", () => {
        if (!$searchInput.value) $searchWrap.classList.remove("expanded");
      });
      $searchInput.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          $searchInput.value = ""; state.search = "";
          $searchWrap.classList.remove("expanded");
          render();
          $searchInput.blur();
        }
      });
    }

    if ($viewBtn && $viewWrap && $viewMenu) {
      $viewBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        $viewWrap.classList.toggle("open");
      });
      $viewMenu.querySelectorAll("button[data-view]").forEach((b) => {
        b.addEventListener("click", () => {
          if (b.disabled) return;
          state.view = b.dataset.view;
          $viewWrap.classList.remove("open");
          render();
        });
      });
      document.addEventListener("click", () => $viewWrap.classList.remove("open"));
    }
  }
  function wireSidebar() {
    const ham = $shell.querySelector(".gcal-hamburger");
    if (ham) ham.addEventListener("click", () => $shell.classList.toggle("rail-closed"));

    const createWrap = $shell.querySelector(".gcal-create");
    const createBtn = createWrap && createWrap.querySelector(".gcal-create-btn");
    if (createBtn && createWrap) {
      createBtn.addEventListener("click", (e) => { e.stopPropagation(); createWrap.classList.toggle("open"); });
      document.addEventListener("click", () => createWrap.classList.remove("open"));
    }

    $shell.querySelectorAll(".gcal-cal-section-head").forEach((head) => {
      head.addEventListener("click", () => {
        const sec = head.closest(".gcal-cal-section");
        if (sec && sec.dataset.section) toggleSection(sec.dataset.section);
      });
    });
    applySectionCollapse();
  }
  function wireKeyboard() {
    document.addEventListener("keydown", (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      switch (e.key) {
        case "t": state.cursor = data.today || dateKey(new Date()); render(); break;
        case "d": state.view = "day"; render(); break;
        case "w": state.view = "week"; render(); break;
        case "m": state.view = "month"; render(); break;
        case "a": state.view = "agenda"; render(); break;
        case "j": step(1); break;
        case "k": step(-1); break;
        case "/":
          if ($searchBtn) {
            e.preventDefault();
            $searchWrap.classList.add("expanded");
            setTimeout(() => $searchInput && $searchInput.focus(), 0);
          }
          break;
        default: return;
      }
    });
  }
  function step(dir) {
    const c = cursorDate();
    if (state.view === "month") c.setMonth(c.getMonth() + dir);
    else if (state.view === "week") c.setDate(c.getDate() + 7 * dir);
    else if (state.view === "day") c.setDate(c.getDate() + dir);
    else c.setMonth(c.getMonth() + dir);
    state.cursor = dateKey(c);
    render();
  }

  // ── DOM / SVG helpers ─────────────────────────────────
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function svgChev(dir, size) {
    const s = size || 20;
    return dir === "left"
      ? `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>`
      : `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>`;
  }
  function svgIcon(name, size) {
    const s = size || 18;
    const attrs = `width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"`;
    switch (name) {
      case "x":
        return `<svg ${attrs}><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
      case "clock":
        return `<svg ${attrs}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`;
      case "calendar":
        return `<svg ${attrs}><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>`;
      case "user":
        return `<svg ${attrs}><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`;
      case "status":
        return `<svg ${attrs}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`;
      case "link":
        return `<svg ${attrs}><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>`;
      case "video":
        return `<svg ${attrs}><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>`;
      case "check":
        return `<svg ${attrs}><polyline points="20 6 9 17 4 12"/></svg>`;
      default:
        return "";
    }
  }
})();
