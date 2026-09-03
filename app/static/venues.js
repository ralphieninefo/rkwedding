const $ = (selector) => document.querySelector(selector);
const directorySummary = $("#directorySummary");
const directoryMessage = $("#directoryMessage");
const venueList = $("#venueList");
const venueSearch = $("#venueSearch");
const venueSort = $("#venueSort");
const comparePanel = $("#comparePanel");
const compareBudget = $("#compareBudget");
const compareRows = $("#compareRows");
const compareHint = $("#compareHint");
const logoutButton = $("#logoutButton");

let allVenues = [];
let budget = null;

const formatDate = (value) => value ? new Date(value).toLocaleString([], {dateStyle: "medium"}) : "—";
const formatEuro = (value) => new Intl.NumberFormat([], {style: "currency", currency: "EUR", maximumFractionDigits: 0}).format(value);
const low = (venue) => venue.price_minimum_eur ?? venue.price_maximum_eur;
const high = (venue) => venue.price_maximum_eur ?? venue.price_minimum_eur;
const priceLabel = (venue) => {
  const min = low(venue);
  const max = high(venue);
  if (min == null) return "";
  return min === max ? formatEuro(min) : `${formatEuro(min)}–${formatEuro(max)}`;
};
const budgetDelta = (venue) => {
  const max = high(venue);
  if (budget == null || max == null) return {text: "", tone: ""};
  const delta = budget - max;
  if (delta >= 0) return {text: `${formatEuro(delta)} under`, tone: "good"};
  return {text: `${formatEuro(-delta)} over`, tone: "warn"};
};

const pillTone = (venue) => {
  if (venue.stage === "closed") return "quiet";
  if (venue.stage === "shortlist") return "good";
  if (venue.attention) return "attention";
  return "";
};

const cell = (text, tone) => {
  const td = document.createElement("td");
  td.textContent = text || "—";
  if (tone) td.dataset.tone = tone;
  return td;
};

const renderCompare = () => {
  const shortlisted = allVenues.filter((venue) => venue.decision === "shortlisted" || (venue.visit_at && venue.decision !== "passed"));
  comparePanel.hidden = shortlisted.length === 0;
  if (!shortlisted.length) return;
  compareBudget.textContent = budget != null
    ? `Budget for the venue: ${formatEuro(budget)} for 90 guests`
    : "Set a budget in Settings to see each quote against it.";
  compareRows.replaceChildren();
  shortlisted
    .slice()
    .sort((left, right) => (high(left) ?? Number.MAX_SAFE_INTEGER) - (high(right) ?? Number.MAX_SAFE_INTEGER))
    .forEach((venue) => {
      const row = document.createElement("tr");
      const name = document.createElement("td");
      const link = document.createElement("a");
      link.href = `/venues/${venue.id}`;
      link.textContent = venue.name;
      name.append(link);
      const delta = budgetDelta(venue);
      row.append(
        name,
        cell(venue.region || venue.location),
        cell(priceLabel(venue) || "No estimate yet"),
        cell(delta.text, delta.tone),
        cell(venue.guest_capacity),
        cell(venue.availability),
        cell(venue.plain_status),
        cell(venue.visit_at ? formatDate(venue.visit_at) : ""),
      );
      compareRows.append(row);
    });
  const missing = shortlisted.filter((venue) => low(venue) == null).length;
  compareHint.textContent = missing
    ? `${missing} shortlisted ${missing === 1 ? "venue has" : "venues have"} no price estimate yet — ask for a quote or open the reply to read it.`
    : "Estimates come from the venues' own replies; verify inclusions before deciding.";
};

const sorted = (venues) => venues.slice().sort((left, right) => {
  const mode = venueSort.value;
  if (mode === "price") return (high(left) ?? Number.MAX_SAFE_INTEGER) - (high(right) ?? Number.MAX_SAFE_INTEGER);
  if (mode === "activity") return new Date(right.last_activity_at || 0) - new Date(left.last_activity_at || 0);
  if (mode === "added") return new Date(right.created_at || 0) - new Date(left.created_at || 0);
  return String(left.name).localeCompare(String(right.name));
});

const renderList = () => {
  const query = venueSearch.value.trim().toLocaleLowerCase();
  const venues = sorted(query
    ? allVenues.filter((venue) => [venue.name, venue.region, venue.location, venue.email, venue.plain_status, venue.availability, venue.guest_capacity, venue.notes, venue.research_notes]
      .some((value) => String(value || "").toLocaleLowerCase().includes(query)))
    : allVenues);
  venueList.replaceChildren();
  venueList.hidden = venues.length === 0;
  directoryMessage.hidden = venues.length > 0;
  if (!venues.length) directoryMessage.textContent = allVenues.length ? "No venues match that search." : "No venues yet. Add one from the Next up page.";
  venues.forEach((venue) => {
    const item = document.createElement("li");
    item.className = "venue-row";
    const name = document.createElement("a");
    name.className = "name";
    name.href = `/venues/${venue.id}`;
    const strong = document.createElement("strong");
    strong.textContent = venue.name;
    const place = document.createElement("small");
    place.textContent = [venue.region, venue.location].filter(Boolean).join(" · ") || venue.email;
    name.append(strong, place);

    const price = document.createElement("div");
    price.className = "cell";
    const delta = budgetDelta(venue);
    if (delta.tone) price.dataset.tone = delta.tone;
    const priceText = priceLabel(venue);
    if (priceText) {
      const b = document.createElement("b");
      b.textContent = priceText;
      price.append(b);
      const small = document.createElement("small");
      small.textContent = delta.text ? `${delta.text} budget` : "for 90 guests";
      price.append(small);
    } else {
      price.textContent = "No estimate yet";
      const small = document.createElement("small");
      small.textContent = venue.guest_capacity ? `Capacity ${venue.guest_capacity}` : "";
      price.append(small);
    }

    const activity = document.createElement("div");
    activity.className = "cell";
    activity.textContent = venue.next_action_label;
    const when = document.createElement("small");
    when.textContent = venue.last_activity_at ? `Last activity ${formatDate(venue.last_activity_at)}` : `Added ${formatDate(venue.created_at)}`;
    activity.append(when);

    const tags = document.createElement("div");
    tags.className = "tags";
    const pill = document.createElement("span");
    pill.className = "status-pill";
    pill.dataset.tone = pillTone(venue);
    pill.textContent = venue.plain_status;
    tags.append(pill);
    if (venue.decision === "shortlisted") {
      const chip = document.createElement("span");
      chip.className = "decision-chip";
      chip.dataset.decision = venue.decision;
      chip.textContent = "Shortlisted";
      tags.append(chip);
    }
    if ((venue.documents || []).length) {
      const docs = document.createElement("span");
      docs.className = "decision-chip";
      docs.textContent = `${venue.documents.length} ${venue.documents.length === 1 ? "file" : "files"}`;
      tags.append(docs);
    }

    item.append(name, price, activity, tags);
    venueList.append(item);
  });
};

const load = async () => {
  const response = await fetch("/api/venues");
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || "Could not load venues.");
  allVenues = result.venues;
  budget = result.preferences?.budget_eur ?? null;
  const shortlisted = allVenues.filter((venue) => venue.decision === "shortlisted").length;
  const priced = allVenues.filter((venue) => low(venue) != null).length;
  directorySummary.textContent = `${allVenues.length} venues · ${priced} with a price estimate · ${shortlisted} shortlisted`;
  renderCompare();
  renderList();
};

venueSearch.addEventListener("input", renderList);
venueSort.addEventListener("input", renderList);
logoutButton.addEventListener("click", async () => {
  await fetch("/api/logout", {method: "POST"});
  window.location.assign("/login");
});

load().catch((error) => { directoryMessage.textContent = error.message; });
