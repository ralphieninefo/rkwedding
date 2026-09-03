const $ = (selector) => document.querySelector(selector);

const queue = $("#queue");
const queueSummary = $("#queueSummary");
const trackerMessage = $("#trackerMessage");
const updateLine = $("#updateLine");
const venueFilter = $("#venueFilter");
const syncPanel = $("#syncPanel");
const syncPanelTitle = $("#syncPanelTitle");
const syncPanelHint = $("#syncPanelHint");
const syncProblems = $("#syncProblems");
const setupPanel = $("#setupPanel");
const settingsButton = $("#settingsButton");
const settingsDialog = $("#settingsDialog");
const accountList = $("#accountList");
const accountMessage = $("#accountMessage");
const connectButton = $("#connectButton");
const budgetForm = $("#budgetForm");
const budgetInput = $("#budgetInput");
const budgetMessage = $("#budgetMessage");
const settingsSync = $("#settingsSync");
const addVenueButton = $("#addVenueButton");
const addVenueDialog = $("#addVenueDialog");
const discoverForm = $("#discoverForm");
const discoverMessage = $("#discoverMessage");
const venueForm = $("#venueForm");
const venueFormMessage = $("#venueFormMessage");
const logoutButton = $("#logoutButton");

const STAGES = [
  {key: "reply_needed", title: "Reply needed", hint: "They answered — read the summary and reply."},
  {key: "waiting", title: "Waiting on venue", hint: "Inquiry sent; a reminder is suggested after a week."},
  {key: "draft", title: "Not contacted yet", hint: "Saved venues that still need the first inquiry."},
  {key: "shortlist", title: "Shortlist", hint: "Venues you like; compare them on the All venues page."},
  {key: "closed", title: "Closed", hint: "Passed or not available."},
];

let allVenues = [];
let accountsState = {connected: false, accounts: []};
let showClosed = false;

const {api, withBusy} = window.VenueActions;

const formatDate = (value, withTime = false) => value
  ? new Date(value).toLocaleString([], withTime ? {dateStyle: "medium", timeStyle: "short"} : {dateStyle: "medium"})
  : "—";

const formatEuro = (value) => new Intl.NumberFormat([], {
  style: "currency", currency: "EUR", maximumFractionDigits: 0,
}).format(value);

const priceLabel = (venue) => {
  const low = venue.price_minimum_eur ?? venue.price_maximum_eur;
  const high = venue.price_maximum_eur ?? venue.price_minimum_eur;
  if (low == null) return "";
  return low === high ? formatEuro(low) : `${formatEuro(low)}–${formatEuro(high)}`;
};

const daysAgo = (days) => {
  if (days == null) return "";
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
};

const showMessage = (text, tone = "success") => {
  trackerMessage.hidden = !text;
  trackerMessage.textContent = text || "";
  trackerMessage.dataset.tone = text ? tone : "";
};

const mailboxShort = (email) => (email ? email.split("@")[0] : "Gmail");

const pillTone = (venue) => {
  if (venue.stage === "closed") return "quiet";
  if (venue.stage === "shortlist") return "good";
  if (venue.attention) return "attention";
  return "";
};

const filteredVenues = () => {
  const query = venueFilter.value.trim().toLocaleLowerCase();
  if (!query) return allVenues;
  return allVenues.filter((venue) => [venue.name, venue.region, venue.location, venue.email]
    .some((value) => String(value || "").toLocaleLowerCase().includes(query)));
};

const sortForStage = (venues, stage) => venues.slice().sort((left, right) => {
  if (stage === "waiting" || stage === "shortlist") {
    return (right.waiting_days ?? -1) - (left.waiting_days ?? -1);
  }
  if (stage === "reply_needed") {
    return new Date(right.responded_at || 0) - new Date(left.responded_at || 0);
  }
  return String(left.name).localeCompare(String(right.name));
});

const renderSummary = (summary, venues) => {
  if (!venues.length) {
    queueSummary.textContent = "No venues yet. Add the first one to start the search.";
    return;
  }
  const parts = [];
  const byStage = summary?.by_stage || {};
  if (byStage.reply_needed) parts.push(`${byStage.reply_needed} need a reply`);
  if (byStage.waiting) parts.push(`${byStage.waiting} waiting on the venue`);
  if (byStage.draft) parts.push(`${byStage.draft} not contacted yet`);
  if (byStage.shortlist) parts.push(`${byStage.shortlist} shortlisted`);
  queueSummary.textContent = parts.length
    ? `${venues.length} venues · ${parts.join(" · ")}`
    : `${venues.length} venues, nothing waiting on you.`;
};

const primaryButton = (label, onClick) => {
  const button = document.createElement("button");
  button.className = "button button-primary";
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", () => onClick(button));
  return button;
};

const secondaryButton = (label, onClick, className = "button button-secondary") => {
  const button = document.createElement("button");
  button.className = className;
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", () => onClick(button));
  return button;
};

const renderCard = (venue) => {
  const card = document.createElement("article");
  card.className = "venue-card";
  card.dataset.attention = String(Boolean(venue.attention));

  const top = document.createElement("div");
  top.className = "card-top";
  const title = document.createElement("a");
  title.className = "card-title";
  title.href = `/venues/${venue.id}`;
  const name = document.createElement("strong");
  name.textContent = venue.name;
  const place = document.createElement("small");
  place.textContent = [venue.region, venue.location].filter(Boolean).join(" · ") || "Region not added";
  title.append(name, place);
  const pill = document.createElement("span");
  pill.className = "status-pill";
  pill.dataset.tone = pillTone(venue);
  pill.textContent = venue.plain_status;
  top.append(title, pill);

  const summary = document.createElement("p");
  summary.className = "card-summary";
  if (venue.response_summary) {
    summary.textContent = venue.response_summary;
  } else if (venue.stage === "draft") {
    summary.textContent = "No inquiry sent yet.";
    summary.dataset.empty = "true";
  } else {
    summary.textContent = "No reply yet.";
    summary.dataset.empty = "true";
  }

  const facts = document.createElement("p");
  facts.className = "card-facts";
  const price = priceLabel(venue);
  if (price) {
    const item = document.createElement("span");
    const bold = document.createElement("b");
    bold.textContent = price;
    item.append(bold, document.createTextNode(" for 90"));
    facts.append(item);
  }
  if (venue.guest_capacity) {
    const item = document.createElement("span");
    item.textContent = `Capacity ${venue.guest_capacity}`;
    facts.append(item);
  }
  if (venue.availability) {
    const item = document.createElement("span");
    item.textContent = venue.availability;
    facts.append(item);
  }
  if (venue.decision === "shortlisted" && venue.stage !== "shortlist") {
    const chip = document.createElement("span");
    chip.className = "decision-chip";
    chip.dataset.decision = "shortlisted";
    chip.textContent = "Shortlisted";
    facts.append(chip);
  }
  if (venue.responded_at && venue.stage === "reply_needed") {
    const item = document.createElement("span");
    item.textContent = `Replied ${daysAgo(venue.days_since_activity)}`;
    facts.append(item);
  } else if (venue.last_reminder_at) {
    const item = document.createElement("span");
    item.textContent = `Reminder sent ${formatDate(venue.last_reminder_at)}`;
    facts.append(item);
  } else if (venue.sent_at && venue.stage !== "reply_needed") {
    const item = document.createElement("span");
    item.textContent = `First e-mail ${formatDate(venue.sent_at)}`;
    facts.append(item);
  }

  const next = document.createElement("p");
  next.className = "next-label";
  next.textContent = venue.next_action_label;
  if (!venue.attention) next.dataset.tone = "quiet";

  const actions = document.createElement("div");
  actions.className = "card-actions";
  if (venue.next_action === "send_inquiry") {
    actions.append(primaryButton("Send inquiry", (button) => openOutreachPreview(venue, button)));
  } else if (venue.next_action === "review_reply") {
    actions.append(primaryButton("Review & reply", (button) => openFollowupPreview(venue, button)));
  } else if (venue.next_action === "send_reminder") {
    actions.append(primaryButton("Send reminder", (button) => openReminderPreview(venue, button)));
  } else if (venue.next_action === "pass") {
    actions.append(secondaryButton("Mark as passed", (button) => setDecision(venue, "passed", button)));
  }
  const links = document.createElement("div");
  links.className = "card-links";
  const details = document.createElement("a");
  details.href = `/venues/${venue.id}`;
  details.textContent = "Details ›";
  links.append(details);
  if (venue.gmail_url) {
    const open = document.createElement("a");
    open.href = venue.gmail_url;
    open.target = "_blank";
    open.rel = "noopener";
    open.textContent = `Open in ${mailboxShort(venue.gmail_account_email)} ↗`;
    open.title = venue.gmail_account_email ? `Opens Gmail as ${venue.gmail_account_email}` : "Opens Gmail";
    links.append(open);
  }
  actions.append(links);

  card.append(top, summary);
  if (facts.childNodes.length) card.append(facts);
  card.append(next, actions);
  return card;
};

const renderQueue = () => {
  const venues = filteredVenues();
  queue.replaceChildren();
  if (!venues.length) {
    showMessage(allVenues.length ? "No venues match that search." : "No venues yet. Tap “Add venue” to start.", "");
    trackerMessage.dataset.tone = "";
    return;
  }
  showMessage("");
  STAGES.forEach((stage) => {
    const members = sortForStage(venues.filter((venue) => venue.stage === stage.key), stage.key);
    if (!members.length) return;
    const section = document.createElement("section");
    section.className = "stage";
    section.dataset.stage = stage.key;
    const heading = document.createElement("div");
    heading.className = "stage-heading";
    const title = document.createElement("h2");
    title.textContent = stage.title;
    const count = document.createElement("small");
    count.textContent = String(members.length);
    title.append(count);
    const hint = document.createElement("p");
    hint.textContent = stage.hint;
    heading.append(title, hint);
    section.append(heading);
    const cards = document.createElement("div");
    cards.className = "cards";
    if (stage.key === "closed" && !showClosed) {
      const toggle = document.createElement("button");
      toggle.className = "stage-toggle";
      toggle.type = "button";
      toggle.textContent = `Show ${members.length} closed ${members.length === 1 ? "venue" : "venues"}`;
      toggle.addEventListener("click", () => { showClosed = true; renderQueue(); });
      heading.replaceChild(toggle, hint);
    } else {
      members.forEach((venue) => cards.append(renderCard(venue)));
      section.append(cards);
      if (stage.key === "closed") {
        const toggle = document.createElement("button");
        toggle.className = "stage-toggle";
        toggle.type = "button";
        toggle.textContent = "Hide closed venues";
        toggle.addEventListener("click", () => { showClosed = false; renderQueue(); });
        heading.replaceChild(toggle, hint);
      }
    }
    queue.append(section);
  });
};

const renderSyncStatus = (syncStatus, lastRefreshedAt) => {
  const accounts = syncStatus?.accounts || [];
  const failed = accounts.filter((account) => account.status === "failed");
  syncProblems.replaceChildren();
  updateLine.textContent = lastRefreshedAt
    ? `Gmail last checked ${formatDate(lastRefreshedAt, true)} · updates every 15 minutes`
    : "Gmail has not been checked yet · updates every 15 minutes";
  settingsButton.dataset.alert = String(failed.length > 0);
  settingsSync.textContent = lastRefreshedAt
    ? `Last successful check: ${formatDate(lastRefreshedAt, true)}. Gmail is checked every 15 minutes.`
    : "No successful check yet. Gmail is checked every 15 minutes once an account is connected.";
  if (!failed.length) {
    syncPanel.hidden = true;
    return;
  }
  failed.forEach((account) => {
    const item = document.createElement("li");
    const mailbox = document.createElement("strong");
    mailbox.textContent = account.email || "Unknown mailbox";
    const detail = document.createElement("span");
    const lastSuccess = account.last_success_at
      ? ` Last successful check: ${formatDate(account.last_success_at, true)}.`
      : " It has not synchronized successfully yet.";
    detail.textContent = ` — ${account.error || "Could not be checked."}${lastSuccess}`;
    item.append(mailbox, detail);
    syncProblems.append(item);
  });
  const healthy = accounts.length - failed.length;
  syncPanelTitle.textContent = failed.length === 1
    ? "One Gmail account needs attention."
    : `${failed.length} Gmail accounts need attention.`;
  syncPanelHint.textContent = healthy > 0
    ? "Automatic updates keep running for the other mailbox. Open Settings and reconnect the mailbox listed above."
    : "Automatic updates are paused until a mailbox is reconnected. Open Settings to reconnect it.";
  syncPanel.hidden = false;
};

const renderAccounts = (syncStatus) => {
  accountList.replaceChildren();
  const statusByEmail = new Map((syncStatus?.accounts || []).map((item) => [item.email, item]));
  if (!accountsState.accounts.length) {
    accountMessage.textContent = "No Gmail account is connected yet.";
    return;
  }
  accountMessage.textContent = "";
  accountsState.accounts.forEach((account) => {
    const item = document.createElement("li");
    const sync = statusByEmail.get(account.email);
    item.dataset.state = sync?.status || "";
    const label = document.createElement("div");
    const email = document.createElement("span");
    email.textContent = account.email;
    const detail = document.createElement("small");
    if (account.is_primary) detail.textContent = "Sends new inquiries";
    if (sync?.status === "failed") detail.textContent = "Needs reconnecting — use the button below.";
    else if (sync?.last_success_at) detail.textContent = `${detail.textContent ? `${detail.textContent} · ` : ""}Last checked ${formatDate(sync.last_success_at, true)}`;
    label.append(email, detail);
    item.append(label);
    accountList.append(item);
  });
};

const loadVenues = async () => {
  const result = await api("/api/venues");
  allVenues = result.venues;
  renderSummary(result.queue, allVenues);
  renderQueue();
  renderSyncStatus(result.sync_status, result.last_refreshed_at);
  renderAccounts(result.sync_status);
  if (result.preferences && budgetInput.value === "" && result.preferences.budget_eur != null) {
    budgetInput.value = String(Math.round(result.preferences.budget_eur));
  }
  return allVenues.length;
};

const loadAccounts = async () => {
  const status = await api("/api/gmail/status");
  accountsState = status;
  setupPanel.hidden = Boolean(status.connected) || !status.oauth_setup_ready;
  connectButton.hidden = !status.oauth_setup_ready;
};

// ----- dialogs (shared with the venue page) ---------------------------------

const actions = window.VenueActions.install({
  onChange: loadVenues,
  onMessage: showMessage,
  primaryMailbox: () => accountsState.accounts.find((account) => account.is_primary)?.email,
});
const {openOutreachPreview, openFollowupPreview, openReminderPreview, setDecision} = actions;

// ----- add venue -----------------------------------------------------------

addVenueButton.addEventListener("click", () => {
  venueForm.reset();
  discoverForm.reset();
  venueFormMessage.textContent = "";
  discoverMessage.textContent = "Paste the website and the app finds the name, e-mail, phone, and region. Or type the details below.";
  addVenueDialog.showModal();
  discoverForm.elements.url.focus();
});

discoverForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = new FormData(discoverForm).get("url");
  if (!url) {
    discoverMessage.textContent = "Paste the venue website first, or fill in the details below.";
    return;
  }
  await withBusy(event.submitter, "Looking…", async () => {
    try {
      const result = await api("/api/venues/discover", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({url}),
      });
      ["name", "region", "location", "email", "website", "phone"].forEach((field) => {
        venueForm.elements[field].value = result[field] || "";
      });
      discoverMessage.textContent = "Found it. Check the details, then save or review the inquiry.";
      venueForm.elements.name.focus();
    } catch (error) {
      discoverMessage.textContent = `${error.message} You can still type the details below.`;
    }
  });
});

venueForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  const reviewAndSend = button?.value === "send";
  const payload = Object.fromEntries(new FormData(venueForm).entries());
  payload.send_now = false;
  await withBusy(button, "Saving…", async () => {
    try {
      const result = await api("/api/venues", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      const savedVenue = {id: result.id, name: payload.name, email: payload.email};
      addVenueDialog.close();
      await loadVenues();
      if (reviewAndSend) {
        await openOutreachPreview(savedVenue, addVenueButton);
      } else {
        showMessage(`${payload.name} saved. It is waiting under “Not contacted yet”.`);
      }
    } catch (error) {
      venueFormMessage.textContent = error.message;
    }
  });
});

// ----- settings ------------------------------------------------------------

settingsButton.addEventListener("click", () => settingsDialog.showModal());
if (window.location.hash === "#settings") {
  window.addEventListener("load", () => settingsDialog.showModal());
}

budgetForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = budgetInput.value.trim();
  await withBusy(event.submitter, "Saving…", async () => {
    try {
      await api("/api/preferences", {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({budget_eur: value ? Number(value) : null}),
      });
      budgetMessage.textContent = "Budget saved. The All venues page compares quotes against it.";
    } catch (error) {
      budgetMessage.textContent = error.message;
    }
  });
});

logoutButton.addEventListener("click", async () => {
  await fetch("/api/logout", {method: "POST"});
  window.location.assign("/login");
});

venueFilter.addEventListener("input", renderQueue);

const boot = async () => {
  try {
    await loadAccounts();
  } catch {
    // The queue still renders from the database when Gmail status is unavailable.
  }
  try {
    await loadVenues();
  } catch (error) {
    showMessage(error.message, "error");
  }
  if (new URLSearchParams(window.location.search).get("connected")) {
    showMessage("Gmail account connected. Automatic updates include it from the next check.");
    window.history.replaceState({}, "", "/");
  }
};

boot();

window.setInterval(() => {
  loadVenues().catch(() => {
    // Keep the last successfully rendered data and try again in one minute.
  });
}, 60_000);
