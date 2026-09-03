const $ = (selector) => document.querySelector(selector);
const {api, withBusy} = window.VenueActions;

const venueId = Number(window.location.pathname.split("/").filter(Boolean).pop());
const pageMessage = $("#pageMessage");
const venueHead = $("#venueHead");
const venueGrid = $("#venueGrid");
const venueName = $("#venueName");
const venuePlace = $("#venuePlace");
const venueChips = $("#venueChips");
const venueNext = $("#venueNext");
const venueActions = $("#venueActions");
const venueSummary = $("#venueSummary");
const venueFacts = $("#venueFacts");
const contactFacts = $("#contactFacts");
const timeline = $("#timeline");
const timelineEmpty = $("#timelineEmpty");
const conversationCount = $("#conversationCount");
const documents = $("#documents");
const documentsEmpty = $("#documentsEmpty");
const documentsCount = $("#documentsCount");
const notesField = $("#notesField");
const notesMessage = $("#notesMessage");
const saveNotes = $("#saveNotes");
const researchText = $("#researchText");
const researchSource = $("#researchSource");
const editResearch = $("#editResearch");
const researchDialog = $("#researchDialog");
const researchForm = $("#researchForm");
const researchMessage = $("#researchMessage");
const editDetails = $("#editDetails");
const detailsDialog = $("#detailsDialog");
const detailsForm = $("#detailsForm");
const detailsMessage = $("#detailsMessage");
const dangerZone = $("#dangerZone");
const deleteVenue = $("#deleteVenue");
const logoutButton = $("#logoutButton");

let venue = null;
let budget = null;
let primaryMailbox = null;

const formatDate = (value, withTime = false) => value
  ? new Date(value).toLocaleString([], withTime ? {dateStyle: "medium", timeStyle: "short"} : {dateStyle: "medium"})
  : "—";
const formatEuro = (value) => new Intl.NumberFormat([], {style: "currency", currency: "EUR", maximumFractionDigits: 0}).format(value);
const formatBytes = (value) => {
  const bytes = Number(value || 0);
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};
const mailboxShort = (email) => (email ? email.split("@")[0] : "Gmail");

const showMessage = (text, tone = "success") => {
  pageMessage.hidden = !text;
  pageMessage.textContent = text || "";
  pageMessage.dataset.tone = text ? tone : "";
};

const actions = window.VenueActions.install({
  onChange: () => load(),
  onMessage: showMessage,
  primaryMailbox: () => primaryMailbox,
});

const fact = (list, label, value, options = {}) => {
  if (value == null || value === "") return;
  const wrap = document.createElement("div");
  const term = document.createElement("dt");
  term.textContent = label;
  const detail = document.createElement("dd");
  if (options.href) {
    const anchor = document.createElement("a");
    anchor.href = options.href;
    anchor.textContent = value;
    if (options.external) { anchor.target = "_blank"; anchor.rel = "noopener"; }
    detail.append(anchor);
  } else {
    detail.textContent = value;
  }
  if (options.tone) detail.dataset.tone = options.tone;
  wrap.append(term, detail);
  list.append(wrap);
};

const priceLabel = (item) => {
  const low = item.price_minimum_eur ?? item.price_maximum_eur;
  const high = item.price_maximum_eur ?? item.price_minimum_eur;
  if (low == null) return "";
  return low === high ? formatEuro(low) : `${formatEuro(low)}–${formatEuro(high)}`;
};

const budgetTone = (item) => {
  const high = item.price_maximum_eur ?? item.price_minimum_eur;
  if (budget == null || high == null) return undefined;
  return high <= budget ? "good" : "warn";
};

const button = (label, className, onClick) => {
  const element = document.createElement("button");
  element.className = className;
  element.type = "button";
  element.textContent = label;
  element.addEventListener("click", () => onClick(element));
  return element;
};

const renderHead = () => {
  venueName.textContent = venue.name;
  venuePlace.textContent = [venue.region, venue.location].filter(Boolean).join(" · ") || "Region not added";
  document.title = `${venue.name} · Wedding Venue Control Center`;
  venueChips.replaceChildren();
  const pill = document.createElement("span");
  pill.className = "status-pill";
  pill.dataset.tone = venue.stage === "closed" ? "quiet" : venue.stage === "shortlist" ? "good" : venue.attention ? "attention" : "";
  pill.textContent = venue.plain_status;
  venueChips.append(pill);
  if (venue.decision) {
    const chip = document.createElement("span");
    chip.className = "decision-chip";
    chip.dataset.decision = venue.decision;
    chip.textContent = venue.decision === "shortlisted" ? "Shortlisted" : "Passed";
    venueChips.append(chip);
  }
  venueNext.textContent = venue.next_action_label;
  venueNext.dataset.tone = venue.attention ? "" : "quiet";

  venueActions.replaceChildren();
  if (venue.next_action === "send_inquiry") {
    venueActions.append(button("Send inquiry", "button button-primary", (element) => actions.openOutreachPreview(venue, element)));
  } else if (venue.next_action === "review_reply") {
    venueActions.append(button("Review & reply", "button button-primary", (element) => actions.openFollowupPreview(venue, element)));
  } else if (venue.next_action === "send_reminder") {
    venueActions.append(button("Send reminder", "button button-primary", (element) => actions.openReminderPreview(venue, element)));
  } else if (venue.inbound_count > 0 && venue.stage !== "closed") {
    venueActions.append(button("Write to them", "button button-secondary", (element) => actions.openFollowupPreview(venue, element)));
  }
  if (venue.gmail_url) {
    const open = document.createElement("a");
    open.className = "button button-link";
    open.href = venue.gmail_url;
    open.target = "_blank";
    open.rel = "noopener";
    open.textContent = `Open in ${mailboxShort(venue.gmail_account_email)} ↗`;
    open.title = venue.gmail_account_email ? `Opens Gmail as ${venue.gmail_account_email}` : "Opens Gmail";
    venueActions.append(open);
  }
  if (venue.decision !== "shortlisted") {
    venueActions.append(button("Shortlist", "button button-secondary", (element) => actions.setDecision(venue, "shortlisted", element)));
  } else {
    venueActions.append(button("Remove from shortlist", "button button-secondary", (element) => actions.setDecision(venue, "", element)));
  }
  if (venue.decision !== "passed") {
    venueActions.append(button("Pass", "button button-secondary", (element) => actions.setDecision(venue, "passed", element)));
  } else {
    venueActions.append(button("Reopen", "button button-secondary", (element) => actions.setDecision(venue, "", element)));
  }
};

const renderFacts = () => {
  venueSummary.textContent = venue.response_summary || (venue.inbound_count ? "Summary not available yet." : "No reply yet.");
  venueSummary.dataset.empty = String(!venue.response_summary);
  venueFacts.replaceChildren();
  const price = priceLabel(venue);
  fact(venueFacts, "Estimate for 90 guests", price ? `${price}${budget != null ? ` · budget ${formatEuro(budget)}` : ""}` : "", {tone: budgetTone(venue)});
  fact(venueFacts, "Price basis", venue.price_note);
  fact(venueFacts, "Capacity", venue.guest_capacity);
  fact(venueFacts, "Availability", venue.availability);
  fact(venueFacts, "Planned visit", venue.visit_at ? formatDate(venue.visit_at) : "");
  fact(venueFacts, "First e-mail", venue.sent_at ? formatDate(venue.sent_at, true) : "Not sent yet");
  fact(venueFacts, "Latest reply", venue.responded_at ? formatDate(venue.responded_at, true) : "No reply yet");
  fact(venueFacts, "Conversation mailbox", venue.gmail_account_email || "");
  fact(venueFacts, "Vibe", venue.vibe);

  contactFacts.replaceChildren();
  fact(contactFacts, "E-mail", venue.email, {href: `mailto:${venue.email}`});
  fact(contactFacts, "Phone", venue.phone, venue.phone ? {href: `tel:${venue.phone}`} : {});
  const website = venue.website && !venue.website.startsWith("http") ? `https://${venue.website}` : venue.website;
  fact(contactFacts, "Website", venue.website, venue.website ? {href: website, external: true} : {});
  fact(contactFacts, "Added", formatDate(venue.created_at));
  dangerZone.hidden = venue.message_count > 0 || Boolean(venue.sent_at);
};

const renderTimeline = () => {
  timeline.replaceChildren();
  const messages = venue.messages || [];
  conversationCount.textContent = messages.length ? `${messages.length} ${messages.length === 1 ? "e-mail" : "e-mails"}` : "";
  timelineEmpty.hidden = messages.length > 0;
  messages.forEach((message) => {
    const item = document.createElement("li");
    item.dataset.direction = message.direction;
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = message.direction === "inbound" ? "V" : "You";
    who.title = message.direction === "inbound" ? "From the venue" : "Sent by you";
    const body = document.createElement("div");
    const meta = document.createElement("p");
    meta.className = "meta";
    const when = document.createElement("span");
    when.textContent = formatDate(message.occurred_at, true);
    const from = document.createElement("span");
    if (message.direction === "inbound") {
      from.append("From ");
      const b = document.createElement("b");
      b.textContent = message.sender_email || venue.email;
      from.append(b);
      if (message.gmail_account_email) from.append(` · received in ${message.gmail_account_email}`);
    } else {
      const label = {inquiry: "First inquiry", reply: "Your reply", reminder: "Reminder"}[message.kind] || "Sent by you";
      from.append(`${label}`);
      if (message.gmail_account_email) {
        from.append(" from ");
        const b = document.createElement("b");
        b.textContent = message.gmail_account_email;
        from.append(b);
      }
    }
    meta.append(when, from);
    const subject = document.createElement("p");
    subject.className = "subject";
    subject.textContent = message.subject || "(no subject)";
    const text = document.createElement("p");
    text.className = "body";
    if (message.summary) {
      text.textContent = message.summary;
    } else {
      text.textContent = message.direction === "inbound" ? "Summary not available — open in Gmail to read it." : "";
      text.dataset.empty = "true";
    }
    body.append(meta, subject, text);
    const links = document.createElement("div");
    links.className = "links";
    (message.documents || []).forEach((doc) => {
      const view = document.createElement("a");
      view.href = doc.view_url;
      view.target = "_blank";
      view.rel = "noopener";
      view.textContent = `📎 ${doc.filename}`;
      links.append(view);
    });
    if (message.gmail_url) {
      const open = document.createElement("a");
      open.href = message.gmail_url;
      open.target = "_blank";
      open.rel = "noopener";
      open.textContent = `Open in ${mailboxShort(message.gmail_account_email)} ↗`;
      links.append(open);
    }
    if (links.childNodes.length) body.append(links);
    item.append(who, body);
    timeline.append(item);
  });
};

const renderDocuments = () => {
  documents.replaceChildren();
  const files = venue.documents || [];
  documentsCount.textContent = files.length ? `${files.length} ${files.length === 1 ? "file" : "files"}` : "";
  documentsEmpty.hidden = files.length > 0;
  files.forEach((doc) => {
    const item = document.createElement("li");
    const info = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = doc.filename;
    const context = document.createElement("small");
    context.textContent = [doc.subject, formatDate(doc.received_at), formatBytes(doc.byte_size), doc.has_text ? "text read for the summary" : ""].filter(Boolean).join(" · ");
    info.append(name, context);
    const links = document.createElement("div");
    const view = document.createElement("a");
    view.href = doc.view_url;
    view.target = "_blank";
    view.rel = "noopener";
    view.textContent = "View";
    links.append(view);
    if (doc.gmail_url) {
      const open = document.createElement("a");
      open.href = doc.gmail_url;
      open.target = "_blank";
      open.rel = "noopener";
      open.textContent = `Open in ${mailboxShort(doc.gmail_account_email)}`;
      links.append(open);
    }
    item.append(info, links);
    documents.append(item);
  });
};

const renderNotes = () => {
  if (document.activeElement !== notesField) notesField.value = venue.notes || "";
  researchText.textContent = venue.research_notes || "No separate research notes yet.";
  researchSource.replaceChildren();
  const bits = [venue.research_source_type, venue.research_contact_name].filter(Boolean).join(" · ");
  if (bits) researchSource.append(document.createTextNode(bits));
  if (venue.research_source_url) {
    const link = document.createElement("a");
    link.href = venue.research_source_url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = " View source ↗";
    researchSource.append(link);
  }
  if (venue.research_updated_at) researchSource.append(document.createTextNode(` · updated ${formatDate(venue.research_updated_at)}`));
  editResearch.textContent = venue.research_notes ? "Edit" : "Add";
};

const render = () => {
  renderHead();
  renderFacts();
  renderTimeline();
  renderDocuments();
  renderNotes();
  venueHead.hidden = false;
  venueGrid.hidden = false;
};

const load = async () => {
  venue = await api(`/api/venues/${venueId}`);
  render();
  return venue;
};

saveNotes.addEventListener("click", () => withBusy(saveNotes, "Saving…", async () => {
  try {
    venue = await api(`/api/venues/${venueId}`, {
      method: "PATCH",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({notes: notesField.value}),
    });
    notesMessage.textContent = "Notes saved.";
    render();
  } catch (error) {
    notesMessage.textContent = error.message;
  }
}));

editDetails.addEventListener("click", () => {
  ["name", "region", "location", "email", "phone", "website", "guest_capacity", "availability", "vibe"].forEach((field) => {
    detailsForm.elements[field].value = venue[field] || "";
  });
  detailsForm.elements.visit_at.value = venue.visit_at ? venue.visit_at.slice(0, 10) : "";
  detailsMessage.textContent = "";
  detailsDialog.showModal();
});

detailsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(detailsForm).entries());
  await withBusy(event.submitter, "Saving…", async () => {
    try {
      venue = await api(`/api/venues/${venueId}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      detailsDialog.close();
      showMessage("Details saved.");
      render();
    } catch (error) {
      detailsMessage.textContent = error.message;
    }
  });
});

editResearch.addEventListener("click", () => {
  researchForm.elements.source_type.value = venue.research_source_type || "Reddit";
  researchForm.elements.source_url.value = venue.research_source_url || "";
  researchForm.elements.contact_name.value = venue.research_contact_name || "";
  researchForm.elements.notes.value = venue.research_notes || "";
  researchMessage.textContent = "Research stays separate from what the venue wrote by e-mail.";
  researchDialog.showModal();
});

researchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(researchForm).entries());
  await withBusy(event.submitter, "Saving…", async () => {
    try {
      await api(`/api/venues/${venueId}/research`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      researchDialog.close();
      await load();
    } catch (error) {
      researchMessage.textContent = error.message;
    }
  });
});

deleteVenue.addEventListener("click", async () => {
  if (!window.confirm(`Delete ${venue.name}? This only works before any e-mail exists.`)) return;
  await withBusy(deleteVenue, "Deleting…", async () => {
    try {
      await api(`/api/venues/${venueId}`, {method: "DELETE"});
      window.location.assign("/");
    } catch (error) {
      showMessage(error.message, "error");
    }
  });
});

logoutButton.addEventListener("click", async () => {
  await fetch("/api/logout", {method: "POST"});
  window.location.assign("/login");
});

const boot = async () => {
  try {
    const [status, preferences] = await Promise.all([
      api("/api/gmail/status").catch(() => ({accounts: []})),
      api("/api/preferences").catch(() => ({})),
    ]);
    primaryMailbox = (status.accounts || []).find((account) => account.is_primary)?.email || null;
    budget = preferences.budget_eur ?? null;
    await load();
    showMessage("");
  } catch (error) {
    showMessage(error.message, "error");
  }
};

boot();
