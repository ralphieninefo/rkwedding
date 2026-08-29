const gmailBadge = document.querySelector("#gmailBadge");
const gmailStatus = document.querySelector("#gmailStatus");
const connectButton = document.querySelector("#connectButton");
const syncButton = document.querySelector("#syncButton");
const setupPanel = document.querySelector("#setupPanel");
const trackedCount = document.querySelector("#trackedCount");
const lastCheck = document.querySelector("#lastCheck");
const lastCheckDetail = document.querySelector("#lastCheckDetail");
const trackerMessage = document.querySelector("#trackerMessage");
const responseTableWrap = document.querySelector("#responseTableWrap");
const responseRows = document.querySelector("#responseRows");

const renderVenues = (venues) => {
  responseRows.replaceChildren();
  venues.forEach((venue) => {
    const row = document.createElement("tr");

    const sender = document.createElement("td");
    sender.className = "sender-cell";
    const senderName = document.createElement("strong");
    senderName.textContent = venue.Venue || "Unnamed venue";
    const region = document.createElement("small");
    region.textContent = venue.Region || "";
    sender.append(senderName, region);

    const location = document.createElement("td");
    location.textContent = venue.Location || "—";

    const email = document.createElement("td");
    email.textContent = venue.Email || "—";

    const sent = document.createElement("td");
    sent.textContent = venue["Date Inquired"] || "—";

    const response = document.createElement("td");
    const responseStrong = document.createElement("strong");
    responseStrong.textContent = venue["Response Received"] || "No";
    const responseSummary = document.createElement("small");
    responseSummary.textContent = venue["Response Summary"] || "";
    response.className = "subject-cell";
    response.append(responseStrong, responseSummary);

    const status = document.createElement("td");
    const pill = document.createElement("span");
    pill.className = "status-pill";
    pill.textContent = venue.Status || "Not set";
    status.append(pill);

    row.append(sender, location, email, sent, response, status);
    responseRows.append(row);
  });

  trackedCount.textContent = venues.length.toLocaleString();
  trackerMessage.hidden = venues.length > 0;
  responseTableWrap.hidden = venues.length === 0;
  if (!venues.length) trackerMessage.textContent = "No venue rows found.";
};

const loadVenues = async () => {
  const response = await fetch("/api/venues");
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || "Could not load the Google Sheet.");
  renderVenues(result.venues);
  return result.venues.length;
};

const checkStatus = async () => {
  const response = await fetch("/api/gmail/status");
  const status = await response.json();
  setupPanel.hidden = status.oauth_setup_ready;

  if (status.connected) {
    gmailStatus.textContent = "Google connected · Sheet + Gmail";
    gmailBadge.classList.remove("badge-muted", "badge-offline");
    connectButton.hidden = true;
    syncButton.disabled = false;
    trackerMessage.textContent = "Loading the Venues tab…";
  } else if (status.oauth_setup_ready) {
    gmailStatus.textContent = "Google not connected";
    connectButton.hidden = false;
  } else {
    gmailStatus.textContent = "Google setup needed";
    connectButton.hidden = true;
  }
  if (status.connected) await loadVenues();
};

syncButton.addEventListener("click", async () => {
  syncButton.disabled = true;
  syncButton.firstChild.textContent = "Refreshing… ";
  try {
    const count = await loadVenues();
    lastCheck.textContent = "Just now";
    lastCheckDetail.textContent = `${count} venue rows loaded`;
  } catch (error) {
    trackerMessage.hidden = false;
    responseTableWrap.hidden = true;
    trackerMessage.textContent = error instanceof Error ? error.message : "Sheet refresh failed.";
  } finally {
    syncButton.disabled = false;
    syncButton.firstChild.textContent = "Refresh from Sheet ";
  }
});

checkStatus().catch(() => {
  gmailStatus.textContent = "Local service unavailable";
  gmailBadge.classList.add("badge-offline");
});
