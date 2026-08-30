const gmailBadge = document.querySelector("#gmailBadge");
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
    if (venue.gmail_url) {
      const reply = document.createElement("a");
      reply.className = "button button-secondary reply-button";
      reply.href = venue.gmail_url;
      reply.target = "_blank";
      reply.rel = "noopener";
      reply.textContent = venue.responded_at
        ? "View reply in Gmail"
        : "Open in Gmail";
      actions.append(reply);
    }

    row.append(identity, region, sent, response, status, actions);
    responseRows.append(row);
  });
  trackedCount.textContent = venues.length.toLocaleString();
  trackerMessage.hidden = venues.length > 0;
  responseTableWrap.hidden = venues.length === 0;
  if (!venues.length) trackerMessage.textContent = "No venues yet. Add one above.";
};

const loadVenues = async () => {
  const response = await fetch("/api/venues");
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || "Could not load venues.");
  renderVenues(result.venues);
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
    ["name", "location", "email", "website", "phone"].forEach((field) => {
      venueForm.elements[field].value = result[field] || "";
    });
    discoverMessage.textContent = "Contact found. Review it, then choose Save venue or Save & send inquiry.";
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
  const payload = Object.fromEntries(new FormData(venueForm).entries());
  payload.send_now = event.submitter?.value === "send";
  venueFormMessage.textContent = payload.send_now ? "Saving and sending…" : "Saving…";
  try {
    const response = await fetch("/api/venues", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not save venue.");
    venueFormMessage.textContent = result.sent
      ? "Inquiry sent and tracked."
      : "Venue saved as a draft.";
    venueForm.reset();
    await loadVenues();
  } catch (error) {
    venueFormMessage.textContent = error instanceof Error
      ? error.message
      : "Could not save venue.";
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
    gmailStatus.textContent = "Gmail connected";
    gmailBadge.classList.remove("badge-muted", "badge-offline");
    connectButton.hidden = true;
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
