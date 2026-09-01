const gmailBadge = document.querySelector("#gmailBadge");
const logoutButton = document.querySelector("#logoutButton");
const gmailStatus = document.querySelector("#gmailStatus");
const connectButton = document.querySelector("#connectButton");
const syncButton = document.querySelector("#syncButton");
const addVenueButton = document.querySelector("#addVenueButton");
const venueFormPanel = document.querySelector("#venueFormPanel");
const venueForm = document.querySelector("#venueForm");
const venueFormMessage = document.querySelector("#venueFormMessage");
const discoverForm = document.querySelector("#discoverForm");
const discoverMessage = document.querySelector("#discoverMessage");
const setupPanel = document.querySelector("#setupPanel");
const trackedCount = document.querySelector("#trackedCount");
const lastCheck = document.querySelector("#lastCheck");
const lastCheckDetail = document.querySelector("#lastCheckDetail");
const trackerMessage = document.querySelector("#trackerMessage");
const responseTableWrap = document.querySelector("#responseTableWrap");
const responseRows = document.querySelector("#responseRows");
const priceEstimate = document.querySelector("#priceEstimate");
const priceEstimateDetail = document.querySelector("#priceEstimateDetail");
const venueFilter = document.querySelector("#venueFilter");
const responseFilter = document.querySelector("#responseFilter");
const venueSort = document.querySelector("#venueSort");
const outreachDialog = document.querySelector("#outreachDialog");
const closeOutreachDialog = document.querySelector("#closeOutreachDialog");
const cancelOutreach = document.querySelector("#cancelOutreach");
const confirmOutreach = document.querySelector("#confirmOutreach");
const outreachRecipient = document.querySelector("#outreachRecipient");
const outreachSubject = document.querySelector("#outreachSubject");
const outreachBody = document.querySelector("#outreachBody");
const outreachDialogMessage = document.querySelector("#outreachDialogMessage");
const followupDialog = document.querySelector("#followupDialog");
const closeFollowupDialog = document.querySelector("#closeFollowupDialog");
const cancelFollowup = document.querySelector("#cancelFollowup");
const confirmFollowup = document.querySelector("#confirmFollowup");
const followupSummary = document.querySelector("#followupSummary");
const followupRecipient = document.querySelector("#followupRecipient");
const followupSubject = document.querySelector("#followupSubject");
const followupBody = document.querySelector("#followupBody");
const followupDialogMessage = document.querySelector("#followupDialogMessage");
let allVenues = [];
let pendingOutreachVenue = null;
let pendingOutreachButton = null;
let pendingOutreachButtonText = "";
let pendingFollowupVenue = null;

const formatDate = (value) => value
  ? new Date(value).toLocaleString([], {dateStyle: "medium", timeStyle: "short"})
  : "—";

const formatEuro = (value) => new Intl.NumberFormat([], {
  style: "currency", currency: "EUR", maximumFractionDigits: 0,
}).format(value);

const renderPriceOverview = (overview) => {
  if (!overview?.venue_count) {
    priceEstimate.textContent = "Not enough data";
    priceEstimateDetail.textContent = "Based on 90 guests";
    return;
  }
  priceEstimate.textContent = `${formatEuro(overview.average_eur)} average`;
  priceEstimateDetail.textContent = `${formatEuro(overview.minimum_eur)}–${formatEuro(overview.maximum_eur)} across ${overview.venue_count} venues`;
};

const renderLastRefresh = (value) => {
  lastCheck.textContent = value ? formatDate(value) : "Not yet";
  lastCheckDetail.textContent = value ? "Last successful Gmail check" : "Use Check Gmail to refresh";
};

const timestamp = (value) => value ? new Date(value).getTime() : 0;

const filteredVenues = () => {
  const query = venueFilter.value.trim().toLocaleLowerCase();
  const filter = responseFilter.value;
  const venues = allVenues.filter((venue) => {
    const matchesQuery = !query || [venue.name, venue.region, venue.location]
      .some((value) => String(value || "").toLocaleLowerCase().includes(query));
    const status = venue.status.toLocaleLowerCase();
    const matchesState = filter === "all"
      || (filter === "responded" && Boolean(venue.responded_at))
      || (filter === "waiting" && Boolean(venue.sent_at) && !venue.responded_at)
      || (filter === "action" && ["more info needed", "quote received", "viewing offered"].includes(status))
      || (filter === "draft" && status === "draft");
    return matchesQuery && matchesState;
  });
  return venues.sort((left, right) => {
    if (venueSort.value === "name") return left.name.localeCompare(right.name);
    if (venueSort.value === "added") return timestamp(right.created_at) - timestamp(left.created_at);
    if (venueSort.value === "reply") return timestamp(right.responded_at) - timestamp(left.responded_at);
    return timestamp(right.last_activity_at) - timestamp(left.last_activity_at);
  });
};

const applyFilters = () => renderVenues(filteredVenues());

const openOutreachPreview = async (venue, button) => {
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Loading draft…";
  try {
    const response = await fetch(`/api/venues/${venue.id}/outreach-preview`);
    const preview = await response.json();
    if (!response.ok) throw new Error(preview.detail || "Could not load inquiry.");
    pendingOutreachVenue = venue;
    pendingOutreachButton = button;
    pendingOutreachButtonText = originalText;
    outreachRecipient.value = preview.recipient;
    outreachSubject.value = preview.subject;
    outreachBody.value = preview.body;
    outreachDialogMessage.textContent = "";
    outreachDialog.showModal();
  } catch (error) {
    trackerMessage.hidden = false;
    trackerMessage.textContent = error instanceof Error
      ? error.message : "Could not load inquiry.";
    button.disabled = false;
    button.textContent = originalText;
    throw error;
  }
};

const openFollowupPreview = async (venue, button) => {
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Loading reply…";
  try {
    const response = await fetch(`/api/venues/${venue.id}/followup-preview`);
    const preview = await response.json();
    if (!response.ok) throw new Error(preview.detail || "Could not prepare reply.");
    pendingFollowupVenue = venue;
    followupSummary.textContent = preview.response_summary || "Response received.";
    followupRecipient.value = preview.recipient;
    followupSubject.value = preview.subject;
    followupBody.value = preview.body;
    followupDialogMessage.textContent = "";
    followupDialog.showModal();
  } catch (error) {
    trackerMessage.hidden = false;
    trackerMessage.textContent = error instanceof Error ? error.message : "Could not prepare reply.";
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
};

const renderVenues = (venues) => {
  responseRows.replaceChildren();
  venues.forEach((venue) => {
    const row = document.createElement("tr");

    const identity = document.createElement("td");
    identity.className = "sender-cell";
    const name = document.createElement("strong");
    name.textContent = venue.name;
    const location = document.createElement("small");
    location.textContent = venue.location || "Location not added";
    identity.append(name, location);

    const region = document.createElement("td");
    region.textContent = venue.region || venue.location || "—";

    const sent = document.createElement("td");
    sent.textContent = formatDate(venue.sent_at);

    const added = document.createElement("td");
    added.textContent = formatDate(venue.created_at);

    const response = document.createElement("td");
    response.className = "subject-cell";
    const replyDate = document.createElement("strong");
    replyDate.textContent = venue.responded_at
      ? formatDate(venue.responded_at)
      : "No response yet";
    const summary = document.createElement("small");
    summary.textContent = venue.response_summary || "";
    response.append(replyDate, summary);

    const status = document.createElement("td");
    const pill = document.createElement("span");
    pill.className = "status-pill";
    pill.textContent = venue.status;
    status.append(pill);

    const actions = document.createElement("td");
    if (venue.status.toLocaleLowerCase() === "draft" && venue.email) {
      const send = document.createElement("button");
      send.className = "button button-secondary reply-button";
      send.type = "button";
      send.textContent = "Send inquiry";
      send.addEventListener("click", () => {
        openOutreachPreview(venue, send).catch(() => {});
      });
      actions.append(send);
    } else if (venue.responded_at) {
      const review = document.createElement("button");
      review.className = "button button-primary reply-button";
      review.type = "button";
      review.textContent = "Review & reply";
      review.addEventListener("click", () => openFollowupPreview(venue, review));
      actions.append(review);
    }
    if (venue.gmail_url) {
      const reply = document.createElement("a");
      reply.className = "button button-secondary reply-button";
      reply.href = venue.gmail_url;
      reply.target = "_blank";
      reply.rel = "noopener";
      reply.textContent = "Open in Gmail";
      actions.append(reply);
    }

    row.append(identity, region, added, sent, response, status, actions);
    responseRows.append(row);
  });
  trackedCount.textContent = allVenues.length.toLocaleString();
  trackerMessage.hidden = venues.length > 0;
  responseTableWrap.hidden = venues.length === 0;
  if (!venues.length) trackerMessage.textContent = allVenues.length
    ? "No venues match these filters."
    : "No venues yet. Add one above.";
};

const closePreview = () => outreachDialog.close();

closeOutreachDialog.addEventListener("click", closePreview);
cancelOutreach.addEventListener("click", closePreview);

outreachDialog.addEventListener("close", () => {
  if (pendingOutreachButton) {
    pendingOutreachButton.disabled = false;
    pendingOutreachButton.textContent = pendingOutreachButtonText;
  }
  pendingOutreachVenue = null;
  pendingOutreachButton = null;
  pendingOutreachButtonText = "";
  confirmOutreach.disabled = false;
  confirmOutreach.textContent = "Send inquiry";
  outreachDialogMessage.textContent = "";
});

confirmOutreach.addEventListener("click", async () => {
  if (!pendingOutreachVenue) return;
  confirmOutreach.disabled = true;
  confirmOutreach.textContent = "Sending…";
  outreachDialogMessage.textContent = "Sending through Gmail…";
  try {
    const response = await fetch(`/api/venues/${pendingOutreachVenue.id}/send`, {
      method: "POST",
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not send inquiry.");
    const venueName = pendingOutreachVenue.name;
    outreachDialog.close();
    trackerMessage.hidden = false;
    trackerMessage.textContent = result.sent
      ? `Inquiry sent to ${venueName}.`
      : `No duplicate sent. Gmail already has a conversation with ${venueName}.`;
    await loadVenues();
  } catch (error) {
    outreachDialogMessage.textContent = error instanceof Error
      ? error.message : "Could not send inquiry.";
    confirmOutreach.disabled = false;
    confirmOutreach.textContent = "Send inquiry";
  }
});

const closeFollowup = () => followupDialog.close();
closeFollowupDialog.addEventListener("click", closeFollowup);
cancelFollowup.addEventListener("click", closeFollowup);
followupDialog.addEventListener("close", () => {
  pendingFollowupVenue = null;
  confirmFollowup.disabled = false;
  confirmFollowup.textContent = "Send reply";
  followupDialogMessage.textContent = "";
});
confirmFollowup.addEventListener("click", async () => {
  if (!pendingFollowupVenue || !followupBody.value.trim()) return;
  confirmFollowup.disabled = true;
  confirmFollowup.textContent = "Sending…";
  followupDialogMessage.textContent = "Sending in the existing Gmail thread…";
  try {
    const response = await fetch(`/api/venues/${pendingFollowupVenue.id}/reply`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({body: followupBody.value.trim()}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not send reply.");
    const venueName = pendingFollowupVenue.name;
    followupDialog.close();
    await loadVenues();
    trackerMessage.hidden = false;
    trackerMessage.textContent = `Reply sent to ${venueName}.`;
  } catch (error) {
    followupDialogMessage.textContent = error instanceof Error ? error.message : "Could not send reply.";
    confirmFollowup.disabled = false;
    confirmFollowup.textContent = "Send reply";
  }
});

[venueFilter, responseFilter, venueSort].forEach((control) => {
  control.addEventListener("input", applyFilters);
});

const loadVenues = async () => {
  const response = await fetch("/api/venues");
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || "Could not load venues.");
  allVenues = result.venues;
  applyFilters();
  renderPriceOverview(result.price_overview);
  renderLastRefresh(result.last_refreshed_at);
  return result.venues.length;
};

discoverForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  discoverMessage.textContent = "Looking for the venue contact…";
  try {
    const response = await fetch("/api/venues/discover", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: new FormData(discoverForm).get("url")}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not inspect that website.");
    venueForm.reset();
    ["name", "region", "location", "email", "website", "phone"].forEach((field) => {
      venueForm.elements[field].value = result[field] || "";
    });
    discoverMessage.textContent = "Contact found. Save it, or review the exact email before sending.";
  } catch (error) {
    discoverMessage.textContent = error instanceof Error ? error.message : "Could not inspect that website.";
  } finally {
    button.disabled = false;
  }
});

addVenueButton.addEventListener("click", () => {
  venueFormPanel.hidden = !venueFormPanel.hidden;
  if (!venueFormPanel.hidden) venueForm.elements.name.focus();
});

venueForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  const reviewAndSend = button?.value === "send";
  const payload = Object.fromEntries(new FormData(venueForm).entries());
  payload.send_now = false;
  button.disabled = true;
  venueFormMessage.textContent = reviewAndSend ? "Saving venue and preparing draft…" : "Saving…";
  try {
    const response = await fetch("/api/venues", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not save venue.");
    const savedVenue = {
      id: result.id,
      name: payload.name,
      email: payload.email,
    };
    venueForm.reset();
    await loadVenues();
    if (reviewAndSend) {
      venueFormMessage.textContent = "Venue saved. Review the draft before sending.";
      await openOutreachPreview(savedVenue, button);
    } else {
      venueFormMessage.textContent = "Venue saved as a draft and added to the dashboard.";
      button.disabled = false;
    }
  } catch (error) {
    venueFormMessage.textContent = error instanceof Error
      ? error.message
      : "Could not save venue.";
    button.disabled = false;
  }
});

syncButton.addEventListener("click", async () => {
  syncButton.disabled = true;
  syncButton.firstChild.textContent = "Checking… ";
  try {
    const response = await fetch("/api/control-center/sync", {method: "POST"});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Gmail check failed.");
    const count = await loadVenues();
    lastCheck.textContent = formatDate(result.last_refreshed_at);
    lastCheckDetail.textContent = `${result.sent_confirmed} sent · ${result.replies_synthesized} new replies · ${count} venues`;
  } catch (error) {
    trackerMessage.hidden = false;
    trackerMessage.textContent = error instanceof Error ? error.message : "Gmail check failed.";
  } finally {
    syncButton.disabled = false;
    syncButton.firstChild.textContent = "Check Gmail ";
  }
});

const checkStatus = async () => {
  const response = await fetch("/api/gmail/status");
  const status = await response.json();
  setupPanel.hidden = status.oauth_setup_ready;
  if (status.connected) {
    const accountCount = status.accounts?.length || 1;
    gmailStatus.textContent = accountCount === 1 ? "1 Gmail connected" : `${accountCount} Gmail accounts`;
    gmailBadge.title = (status.accounts || []).map((account) => account.email).join("\n");
    gmailBadge.classList.remove("badge-muted", "badge-offline");
    connectButton.hidden = false;
    syncButton.disabled = false;
  } else if (status.oauth_setup_ready) {
    gmailStatus.textContent = "Google not connected";
    connectButton.hidden = false;
  } else {
    gmailStatus.textContent = "Google setup needed";
    connectButton.hidden = true;
  }
  let count = await loadVenues();
  if (!count && status.connected && status.spreadsheet_configured) {
    const imported = await fetch("/api/import/sheet", {method: "POST"});
    if (imported.ok) count = await loadVenues();
  }
  return count;
};

checkStatus().catch(() => {
  gmailStatus.textContent = "Local service unavailable";
  gmailBadge.classList.add("badge-offline");
});

logoutButton.addEventListener("click", async () => {
  await fetch("/api/logout", {method: "POST"});
  window.location.assign("/login");
});

window.setInterval(() => {
  loadVenues().catch(() => {
    // Keep the last successfully rendered data and try again in one minute.
  });
}, 60_000);
