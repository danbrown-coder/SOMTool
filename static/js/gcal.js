/* Google Calendar-style outreach view engine.
 *
 * Consumes a JSON blob embedded by outreach_schedule.html:
 *   window.__GCAL_DATA__ = { items, events, palette, today, urls }
 *
 * Renders four views (Month / Week / Day / Agenda), a mini-month on the
 * left rail, a "My calendars" list driving chip visibility, a click
 * popover, and Google-parity keyboard shortcuts (t / d / w / m / a /
 * j / k / /). View + cursor + hidden calendars persist to localStorage
 * so refresh keeps context.
 */

(function () {
  "use strict";

  const data = window.__GCAL_DATA__ || { items: [], events: [], palette: {}, today: null, urls: {} };
  const PALETTE = ["tomato","flamingo","tangerine","banana","sage","basil","peacock","blueberry","lavender","grape","graphite","lime"];
  const DOW = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
  const DOW_SHORT = ["S","M","T","W","T","F","S"];
  const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  const STORE_KEY = "gcal.state.v1";
  const HOUR_PX = 48;

  const state = loadState();
  const items = data.items.map(parseItem).sort((a, b) => a.start - b.start);
  const eventsById = Object.fromEntries(data.events.map((e) => [e.id, e]));
  const allItemsByKey = indexItemsByDate(items);

  // DOM refs
  const $shell = document.querySelector(".gcal-shell");
  if (!$shell) return;
  const $canvas = $shell.querySelector(".gcal-canvas");
  const $range = $shell.querySelector(".gcal-range");
  const $mini = $shell.querySelector(".gcal-mini");
  const $calList = $shell.querySelector(".gcal-cal-list-events");
  const $calListStatus = $shell.querySelector(".gcal-cal-list-status");
  const $search = $shell.querySelector(".gcal-search input");
  const $viewSwitch = $shell.querySelector(".gcal-view-switch");
  const $popover = document.getElementById("gcal-popover");

  const urls = data.urls || {};

  // ── Init ───────────────────────────────────────────────
  wireTopbar();
  wireViewSwitch();
  wireSidebar();
  wireKeyboard();
  wirePopoverDismiss();
  renderCalendarList();
  render();

  // Keep now-line live in Week/Day
  setInterval(() => { if (state.view === "week" || state.view === "day") positionNowLine(); }, 60000);

  // ── State helpers ──────────────────────────────────────
  function loadState() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (raw) {
        const s = JSON.parse(raw);
        return {
          view: s.view || "month",
          cursor: s.cursor || data.today,
          hiddenEvents: Array.isArray(s.hiddenEvents) ? s.hiddenEvents : [],
          hiddenStatuses: Array.isArray(s.hiddenStatuses) ? s.hiddenStatuses : [],
          search: "",
        };
      }
    } catch (e) { /* ignore */ }
    return { view: "month", cursor: data.today, hiddenEvents: [], hiddenStatuses: [], search: "" };
  }
  function saveState() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        view: state.view, cursor: state.cursor,
        hiddenEvents: state.hiddenEvents, hiddenStatuses: state.hiddenStatuses,
      }));
    } catch (e) { /* ignore */ }
  }

  function parseItem(raw) {
    const start = new Date(raw.scheduled_at);
    const end = new Date(start.getTime() + 30 * 60 * 1000);
    return {
      ...raw,
      start,
      end,
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

  // ── Date helpers ───────────────────────────────────────
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
  function sameDay(a, b) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
  function addDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
  function startOfWeek(d) { const x = new Date(d); x.setDate(x.getDate() - x.getDay()); return x; }
  function fmtTime(d) {
    let h = d.getHours();
    const m = d.getMinutes();
    const ampm = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    return m === 0 ? `${h} ${ampm}` : `${h}:${String(m).padStart(2, "0")} ${ampm}`;
  }
  function fmtHour(h) {
    if (h === 0) return "";
    const ampm = h >= 12 ? "PM" : "AM";
    const hh = h % 12 || 12;
    return `${hh} ${ampm}`;
  }

  // ── Visibility filter ──────────────────────────────────
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

  // ── Render root ────────────────────────────────────────
  function render() {
    renderRange();
    renderViewSwitch();
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
        $range.textContent = `${MONTHS[s.getMonth()]} ${s.getDate()} \u2013 ${e.getDate()}, ${e.getFullYear()}`;
      } else {
        $range.textContent = `${MONTHS[s.getMonth()].slice(0,3)} ${s.getDate()} \u2013 ${MONTHS[e.getMonth()].slice(0,3)} ${e.getDate()}, ${e.getFullYear()}`;
      }
    } else if (state.view === "day") {
      $range.textContent = `${MONTHS[c.getMonth()]} ${c.getDate()}, ${c.getFullYear()}`;
    } else {
      $range.textContent = "Schedule";
    }
  }

  function renderViewSwitch() {
    $viewSwitch.querySelectorAll("button").forEach((b) => {
      b.classList.toggle("active", b.dataset.view === state.view);
    });
  }

  // ── Mini-month ─────────────────────────────────────────
  function renderMini() {
    const c = cursorDate();
    const first = new Date(c.getFullYear(), c.getMonth(), 1);
    const gridStart = addDays(first, -first.getDay());
    let html = `<div class="gcal-mini-head">
      <div class="gcal-mini-title">${MONTHS[c.getMonth()]} ${c.getFullYear()}</div>
      <div class="gcal-mini-nav">
        <button type="button" aria-label="Previous month" data-mini="-1">${chev("left")}</button>
        <button type="button" aria-label="Next month" data-mini="1">${chev("right")}</button>
      </div>
    </div>
    <div class="gcal-mini-grid">`;
    DOW_SHORT.forEach((d) => { html += `<div class="gcal-mini-dow">${d}</div>`; });
    const today = todayDate();
    for (let i = 0; i < 42; i++) {
      const d = addDays(gridStart, i);
      const classes = ["gcal-mini-day"];
      if (d.getMonth() !== c.getMonth()) classes.push("other");
      if (sameDay(d, today)) classes.push("today");
      if (sameDay(d, c)) classes.push("selected");
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
        renderMini(); renderRange();
      });
    });
  }

  // ── Calendar list (My calendars + Other calendars) ─────
  function renderCalendarList() {
    $calList.innerHTML = "";
    data.events.forEach((ev) => {
      const off = state.hiddenEvents.includes(ev.id);
      const li = document.createElement("li");
      li.className = "gcal-cal-item c-" + (ev.color || "peacock") + (off ? " off" : "");
      li.innerHTML = `
        <span class="swatch"></span>
        <span class="gcal-cal-name" title="${escapeHtml(ev.name)}">${escapeHtml(ev.name)}</span>
        <span class="gcal-cal-count">${ev.count || 0}</span>`;
      li.addEventListener("click", () => {
        const idx = state.hiddenEvents.indexOf(ev.id);
        if (idx >= 0) state.hiddenEvents.splice(idx, 1);
        else state.hiddenEvents.push(ev.id);
        renderCalendarList(); render();
      });
      $calList.appendChild(li);
    });

    if (!$calListStatus) return;
    $calListStatus.innerHTML = "";
    [
      { id: "planned", label: "Planned", color: "graphite" },
      { id: "approved", label: "Approved", color: "basil" },
      { id: "sent", label: "Sent", color: "peacock" },
      { id: "skipped", label: "Skipped / failed", color: "tomato" },
    ].forEach((s) => {
      const off = state.hiddenStatuses.includes(s.id) || (s.id === "skipped" && state.hiddenStatuses.includes("failed"));
      const li = document.createElement("li");
      li.className = "gcal-cal-item c-" + s.color + (off ? " off" : "");
      li.innerHTML = `<span class="swatch"></span><span class="gcal-cal-name">${s.label}</span>`;
      li.addEventListener("click", () => {
        const ids = s.id === "skipped" ? ["skipped", "failed"] : [s.id];
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

  // ── Month view ─────────────────────────────────────────
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

      const num = el("div", "gcal-month-daynum"); num.textContent = d.getDate();
      num.addEventListener("click", () => { state.cursor = key; state.view = "day"; render(); });
      cell.appendChild(num);

      const chips = el("div", "gcal-month-chips");
      const dayItems = (byKey[key] || []).slice().sort((a,b) => a.start - b.start);
      const MAX = 3;
      dayItems.slice(0, MAX).forEach((it) => chips.appendChild(monthChip(it)));
      if (dayItems.length > MAX) {
        const more = el("div", "gcal-month-more");
        more.textContent = `+${dayItems.length - MAX} more`;
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
    const status = it.status || "planned";
    const filled = status === "approved" || status === "sent";
    const chip = el("div", "gcal-chip " + (filled ? "filled" : "outlined") + " " + status + " c-" + (it.color || "peacock"));
    if (filled) {
      chip.innerHTML = `<span class="chip-time">${fmtTime(it.start)}</span><span class="chip-title">${escapeHtml(chipTitle(it))}</span>`;
    } else {
      chip.innerHTML = `<span class="chip-dot"></span><span class="chip-time">${fmtTime(it.start)}</span><span class="chip-title">${escapeHtml(chipTitle(it))}</span>`;
    }
    chip.addEventListener("click", (e) => { e.stopPropagation(); openPopover(it, chip); });
    return chip;
  }
  function chipTitle(it) {
    const action = humanAction(it.action_type);
    if (it.contact_name) return `${action} \u00b7 ${it.contact_name}`;
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

  // ── Week / Day view ────────────────────────────────────
  function renderWeek(cols) {
    const c = cursorDate();
    const start = cols === 7 ? startOfWeek(c) : c;
    const days = [];
    for (let i = 0; i < cols; i++) days.push(addDays(start, i));
    const today = todayDate();
    const vis = visibleItems();

    const wrap = el("div", "gcal-week");
    wrap.style.setProperty("--cols", cols);

    // Day header
    const header = el("div", "gcal-week-header");
    header.appendChild(el("div", "gcal-week-corner"));
    days.forEach((d) => {
      const dh = el("div", "gcal-week-dayhead");
      if (sameDay(d, today)) dh.classList.add("today");
      dh.innerHTML = `<div class="dow">${DOW[d.getDay()].toUpperCase()}</div><div class="daynum">${d.getDate()}</div>`;
      dh.addEventListener("click", () => { state.cursor = dateKey(d); state.view = "day"; render(); });
      header.appendChild(dh);
    });
    wrap.appendChild(header);

    // All-day row (we place any items flagged as all-day here; scheduled_at has times so usually empty)
    const allday = el("div", "gcal-week-allday");
    allday.appendChild(el("div", "gcal-week-allday-label", "all-day"));
    days.forEach(() => allday.appendChild(el("div", "gcal-week-allday-cell")));
    wrap.appendChild(allday);

    // Scrollable body
    const scroll = el("div", "gcal-week-scroll");
    const grid = el("div", "gcal-week-grid");

    // Hour labels column
    const hours = el("div", "gcal-hour-labels");
    for (let h = 0; h < 24; h++) {
      hours.appendChild(el("div", "gcal-hour-label", fmtHour(h)));
    }
    grid.appendChild(hours);

    // Day columns
    days.forEach((d) => {
      const col = el("div", "gcal-day-col");
      if (sameDay(d, today)) col.classList.add("today-col");
      for (let h = 0; h < 24; h++) col.appendChild(el("div", "gcal-hour-slot"));
      const dayItems = vis.filter((it) => sameDay(it.start, d));
      packBlocks(dayItems).forEach((b) => col.appendChild(renderBlock(b)));
      grid.appendChild(col);
    });

    scroll.appendChild(grid);
    wrap.appendChild(scroll);
    $canvas.appendChild(wrap);

    // Scroll to a sensible position (7am or now)
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
      <div class="block-title">${escapeHtml(humanAction(it.action_type))}${it.contact_name ? " \u00b7 " + escapeHtml(it.contact_name) : ""}</div>
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
    cols.forEach((col, idx) => {
      const day = headerDayAt(wrap, idx);
      if (!day) return;
      if (!sameDay(day, now)) return;
      const line = el("div", "gcal-now-line");
      line.style.top = ((now.getHours() + now.getMinutes() / 60) * HOUR_PX) + "px";
      col.appendChild(line);
    });
  }
  function headerDayAt(wrap, idx) {
    const heads = wrap.querySelectorAll(".gcal-week-dayhead");
    return heads[idx] ? parseHead(heads[idx]) : null;
  }
  function parseHead(el) {
    // reverse from DOM: rebuild by reading .daynum + nearest month from range
    // Simpler: iterate children of the week header and compute from cursor.
    const wrap = el.closest(".gcal-week");
    const cols = Number(wrap.style.getPropertyValue("--cols") || 7);
    const heads = Array.from(wrap.querySelectorAll(".gcal-week-dayhead"));
    const idx = heads.indexOf(el);
    const c = cursorDate();
    const start = cols === 7 ? startOfWeek(c) : c;
    return addDays(start, idx);
  }

  // ── Agenda view ────────────────────────────────────────
  function renderAgenda() {
    const vis = visibleItems();
    const wrap = el("div", "gcal-agenda");
    if (vis.length === 0) {
      wrap.appendChild(el("div", "gcal-agenda-empty", "No scheduled outreach. Use Plan outreach to queue actions."));
      $canvas.appendChild(wrap);
      return;
    }
    const byKey = indexItemsByDate(vis);
    const keys = Object.keys(byKey).sort();
    const today = todayDate();
    keys.forEach((k) => {
      const d = parseISODate(k);
      const header = el("div", "gcal-agenda-date");
      if (sameDay(d, today)) header.classList.add("today");
      header.innerHTML = `<span>${MONTHS[d.getMonth()].slice(0,3)} ${d.getDate()}</span><span class="dayname">${DOW[d.getDay()]}${sameDay(d, today) ? " \u00b7 Today" : ""}</span>`;
      wrap.appendChild(header);
      byKey[k].sort((a,b) => a.start - b.start).forEach((it) => wrap.appendChild(agendaRow(it)));
    });
    $canvas.appendChild(wrap);
  }
  function agendaRow(it) {
    const row = el("div", "gcal-agenda-row c-" + (it.color || "peacock"));
    row.innerHTML = `
      <div class="gcal-agenda-time">${fmtTime(it.start)}</div>
      <div class="gcal-agenda-dot"></div>
      <div class="gcal-agenda-title">
        <span>${escapeHtml(humanAction(it.action_type))}${it.contact_name ? " \u00b7 " + escapeHtml(it.contact_name) : ""}</span>
        <span class="meta">${escapeHtml(it.event_name || "")}</span>
      </div>
      <div class="gcal-agenda-status ${it.status}">${it.status}</div>`;
    row.addEventListener("click", () => openPopover(it, row));
    return row;
  }

  // ── Popover ────────────────────────────────────────────
  function openPopover(it, anchor) {
    closePopover();
    const color = "c-" + (it.color || "peacock");
    const ev = eventsById[it.event_id];
    const approveUrl = (urls.approve || "/outreach/queue/__id__/approve").replace("__id__", it.id);
    const skipUrl = (urls.skip || "/outreach/queue/__id__/skip").replace("__id__", it.id);
    const deleteUrl = (urls.del || "/outreach/queue/__id__/delete").replace("__id__", it.id);
    const csrf = (urls.csrf || "");
    const eventUrl = ev && urls.event ? urls.event.replace("__id__", ev.id) : null;

    $popover.className = "gcal-popover open " + color;
    $popover.innerHTML = `
      <div class="gcal-pop-bar"></div>
      <div class="gcal-pop-head">
        <div class="gcal-pop-swatch"></div>
        <div class="gcal-pop-title">${escapeHtml(humanAction(it.action_type))}${it.contact_name ? " \u00b7 " + escapeHtml(it.contact_name) : ""}</div>
        <button class="gcal-pop-close" type="button" aria-label="Close">${icon("x")}</button>
      </div>
      <div class="gcal-pop-meta">
        <div>${fmtAgendaDate(it.start)} \u00b7 ${fmtTime(it.start)}</div>
        ${ev ? `<div>Event: ${eventUrl ? `<a href="${eventUrl}">${escapeHtml(ev.name)}</a>` : escapeHtml(ev.name)}</div>` : ""}
        ${it.contact_email ? `<div>To: <a href="mailto:${escapeHtml(it.contact_email)}">${escapeHtml(it.contact_email)}</a></div>` : ""}
        <div>Status: <strong>${it.status}</strong></div>
      </div>
      ${it.preview ? `<div class="gcal-pop-body">${escapeHtml(it.preview)}</div>` : ""}
      <div class="gcal-pop-actions">
        ${it.status !== "skipped" && it.status !== "failed" && it.status !== "sent" ? `<form method="post" action="${skipUrl}"><input type="hidden" name="csrf_token" value="${csrf}">${hiddenReturn()}<button class="gcal-btn" type="submit">Skip</button></form>` : ""}
        ${it.status === "planned" ? `<form method="post" action="${approveUrl}"><input type="hidden" name="csrf_token" value="${csrf}">${hiddenReturn()}<button class="gcal-btn primary" type="submit">Approve</button></form>` : ""}
        <form method="post" action="${deleteUrl}" onsubmit="return confirm('Delete this action?');"><input type="hidden" name="csrf_token" value="${csrf}">${hiddenReturn()}<button class="gcal-btn danger" type="submit">Delete</button></form>
      </div>`;

    $popover.querySelector(".gcal-pop-close").addEventListener("click", closePopover);

    // Position the popover near the anchor, clamped into viewport
    const a = anchor.getBoundingClientRect();
    const pw = 360, ph = Math.min(420, window.innerHeight - 40);
    let left = a.right + 8;
    if (left + pw > window.innerWidth - 8) left = Math.max(8, a.left - pw - 8);
    let top = a.top;
    if (top + ph > window.innerHeight - 8) top = Math.max(8, window.innerHeight - ph - 8);
    $popover.style.left = left + "px";
    $popover.style.top = top + "px";
  }
  function closePopover() {
    if ($popover) { $popover.classList.remove("open"); $popover.innerHTML = ""; }
  }
  function wirePopoverDismiss() {
    document.addEventListener("click", (e) => {
      if (!$popover.contains(e.target)) closePopover();
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePopover(); });
  }
  function hiddenReturn() { return `<input type="hidden" name="return_to" value="">`; }
  function fmtAgendaDate(d) {
    return `${DOW[d.getDay()]}, ${MONTHS[d.getMonth()]} ${d.getDate()}`;
  }

  // ── Topbar / sidebar / shortcuts ───────────────────────
  function wireTopbar() {
    $shell.querySelector(".gcal-today-btn").addEventListener("click", () => {
      state.cursor = data.today || dateKey(new Date());
      render();
    });
    const [prev, next] = $shell.querySelectorAll(".gcal-nav button");
    prev.addEventListener("click", () => { step(-1); });
    next.addEventListener("click", () => { step(1); });
    if ($search) {
      $search.addEventListener("input", () => { state.search = $search.value; render(); });
      $search.addEventListener("keydown", (e) => { if (e.key === "Escape") { $search.value = ""; state.search = ""; render(); $search.blur(); } });
    }
  }
  function wireViewSwitch() {
    $viewSwitch.querySelectorAll("button").forEach((b) => {
      b.addEventListener("click", () => { state.view = b.dataset.view; render(); });
    });
  }
  function wireSidebar() {
    const ham = $shell.querySelector(".gcal-hamburger");
    if (ham) ham.addEventListener("click", () => $shell.classList.toggle("rail-closed"));
    const createBtn = $shell.querySelector(".gcal-create-btn");
    const createWrap = $shell.querySelector(".gcal-create");
    if (createBtn && createWrap) {
      createBtn.addEventListener("click", (e) => { e.stopPropagation(); createWrap.classList.toggle("open"); });
      document.addEventListener("click", () => createWrap.classList.remove("open"));
    }
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
        case "j": case "ArrowRight": if (e.key === "j" || e.shiftKey) { step(1); } else return; break;
        case "k": case "ArrowLeft": if (e.key === "k" || e.shiftKey) { step(-1); } else return; break;
        case "/": if ($search) { e.preventDefault(); $search.focus(); } break;
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

  // ── Tiny DOM helpers ───────────────────────────────────
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
  function chev(dir) {
    return dir === "left"
      ? `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>`
      : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>`;
  }
  function icon(name) {
    if (name === "x") return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
    return "";
  }
})();
