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

const renderResponses = (responses) => {
  responseRows.replaceChildren();
  responses.forEach((response) => {
    const row = document.createElement("tr");

    const sender = document.createElement("td");
    sender.className = "sender-cell";
    const senderName = document.createElement("strong");
    senderName.textContent = response.sender_name;
    const senderEmail = document.createElement("small");
    senderEmail.textContent = response.sender_email;
    sender.append(senderName, senderEmail);

    const subject = document.createElement("td");
    subject.className = "subject-cell";
    const subjectText = document.createElement("strong");
    subjectText.textContent = response.subject;
    const snippet = document.createElement("small");
    snippet.textContent = response.snippet;
    subject.append(subjectText, snippet);

    const received = document.createElement("td");
    received.textContent = new Date(response.received_at).toLocaleString();

    const status = document.createElement("td");
    const pill = document.createElement("span");
    pill.className = "status-pill";
    pill.textContent = response.tracking_status;
    status.append(pill);

    row.append(sender, subject, received, status);
    responseRows.append(row);
  });

  trackedCount.textContent = responses.length.toLocaleString();
  trackerMessage.hidden = responses.length > 0;
  responseTableWrap.hidden = responses.length === 0;
  if (!responses.length) trackerMessage.textContent = "No replies are tracked yet.";
};

const loadResponses = async () => {
  const response = await fetch("/api/responses");
  if (!response.ok) throw new Error("Could not load tracked responses.");
  renderResponses((await response.json()).responses);
};

const checkStatus = async () => {
  const response = await fetch("/api/gmail/status");
  const status = await response.json();
  setupPanel.hidden = status.oauth_setup_ready;

  if (status.connected) {
    gmailStatus.textContent = "Gmail connected · read only";
    gmailBadge.classList.remove("badge-muted", "badge-offline");
    connectButton.hidden = true;
    syncButton.disabled = false;
    trackerMessage.textContent = "Click “Check for replies” to scan recent conversations.";
  } else if (status.oauth_setup_ready) {
    gmailStatus.textContent = "Gmail not connected";
    connectButton.hidden = false;
  } else {
    gmailStatus.textContent = "Google setup needed";
    connectButton.hidden = true;
  }
  await loadResponses();
};

syncButton.addEventListener("click", async () => {
  syncButton.disabled = true;
  syncButton.firstChild.textContent = "Checking… ";
  try {
    const response = await fetch("/api/gmail/sync", {method: "POST"});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Gmail sync failed.");
    lastCheck.textContent = "Just now";
    lastCheckDetail.textContent = `${result.new_responses} new · ${result.threads_checked} threads checked`;
    await loadResponses();
  } catch (error) {
    trackerMessage.hidden = false;
    responseTableWrap.hidden = true;
    trackerMessage.textContent = error instanceof Error ? error.message : "Gmail sync failed.";
  } finally {
    syncButton.disabled = false;
    syncButton.firstChild.textContent = "Check for replies ";
  }
});

checkStatus().catch(() => {
  gmailStatus.textContent = "Local service unavailable";
  gmailBadge.classList.add("badge-offline");
});
