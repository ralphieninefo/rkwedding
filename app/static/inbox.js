const gmailBadge = document.querySelector("#gmailBadge");
const gmailStatus = document.querySelector("#gmailStatus");
const connectButton = document.querySelector("#connectButton");
const syncButton = document.querySelector("#syncButton");
const addVenueButton = document.querySelector("#addVenueButton");
const venueFormPanel = document.querySelector("#venueFormPanel");
const venueForm = document.querySelector("#venueForm");
const venueFormMessage = document.querySelector("#venueFormMessage");
const setupPanel = document.querySelector("#setupPanel");
const trackedCount = document.querySelector("#trackedCount");
const lastCheck = document.querySelector("#lastCheck");
const lastCheckDetail = document.querySelector("#lastCheckDetail");
const trackerMessage = document.querySelector("#trackerMessage");
const responseTableWrap = document.querySelector("#responseTableWrap");
const responseRows = document.querySelector("#responseRows");

const formatDate = (value) => value
  ? new Date(value).toLocaleString([], {dateStyle: "medium", timeStyle: "short"})
  : "—";

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

    const contact = document.createElement("td");
    contact.className = "subject-cell";
    const email = document.createElement("strong");
    email.textContent = venue.email;
    const details = document.createElement("small");
    details.textContent = [venue.phone, venue.website].filter(Boolean).join(" · ") || "—";
    contact.append(email, details);

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

    row.append(identity, contact, sent, response, status);
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
  return result.venues.length;
};

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
    lastCheck.textContent = "Just now";
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
    lastCheckDetail.textContent = "Use Check Gmail to refresh";
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
