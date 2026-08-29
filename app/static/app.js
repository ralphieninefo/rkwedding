const form = document.querySelector("#analysisForm");
const venueInput = document.querySelector("#venue");
const threadInput = document.querySelector("#threadId");
const messageInput = document.querySelector("#message");
const characterCount = document.querySelector("#characterCount");
const analyzeButton = document.querySelector("#analyzeButton");
const sampleButton = document.querySelector("#sampleButton");
const clearButton = document.querySelector("#clearButton");

const serverBadge = document.querySelector("#serverBadge");
const serverStatus = document.querySelector("#serverStatus");
const inferenceBadge = document.querySelector("#inferenceBadge");
const inferenceStatus = document.querySelector("#inferenceStatus");

const decisionEmpty = document.querySelector("#decisionEmpty");
const decisionResult = document.querySelector("#decisionResult");
const decisionError = document.querySelector("#decisionError");
const errorMessage = document.querySelector("#errorMessage");
const resultStatus = document.querySelector("#resultStatus");
const resultVenue = document.querySelector("#resultVenue");
const resultEvent = document.querySelector("#resultEvent");
const resultQuote = document.querySelector("#resultQuote");
const resultAction = document.querySelector("#resultAction");
const resultCallout = document.querySelector("#resultCallout");

const humanize = (value) => {
  if (!value) return "—";
  return String(value).replaceAll("_", " ");
};

const updateCount = () => {
  const count = messageInput.value.length;
  characterCount.textContent = `${count.toLocaleString()} character${count === 1 ? "" : "s"}`;
};

const setView = (view) => {
  decisionEmpty.hidden = view !== "empty";
  decisionResult.hidden = view !== "result";
  decisionError.hidden = view !== "error";
};

const checkHealth = async () => {
  try {
    const response = await fetch("/health", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`Health check returned ${response.status}`);
    const data = await response.json();

    serverStatus.textContent = "Local service online";
    serverBadge.classList.remove("badge-offline");

    if (data.inference === "configured") {
      inferenceStatus.textContent = "Inference configured";
      inferenceBadge.classList.remove("badge-muted", "badge-offline");
    } else {
      inferenceStatus.textContent = "Inference not configured";
      inferenceBadge.classList.add("badge-muted");
    }
  } catch (error) {
    serverStatus.textContent = "Local service offline";
    serverBadge.classList.add("badge-offline");
    inferenceStatus.textContent = "Inference unavailable";
    inferenceBadge.classList.add("badge-muted");
  }
};

const renderDecision = (data) => {
  resultStatus.textContent = humanize(data.status);
  resultVenue.textContent = data.venue || "—";
  resultEvent.textContent = humanize(data.event_type);
  resultAction.textContent = humanize(data.recommended_action);

  if (data.quoted_price != null) {
    const currency = data.currency || "EUR";
    resultQuote.textContent = new Intl.NumberFormat("en", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(data.quoted_price);
  } else {
    resultQuote.textContent = "Not extracted";
  }

  if (data.event_type === "unprocessed") {
    resultCallout.textContent =
      "The local dashboard and webhook are working. Connect DigitalOcean Serverless Inference to classify the message and extract the quote.";
  } else {
    resultCallout.textContent =
      "The result is advisory. Review any draft before sending or making a commitment.";
  }

  setView("result");
};

messageInput.addEventListener("input", updateCount);

sampleButton.addEventListener("click", () => {
  venueInput.value = "Villa Test";
  threadInput.value = "";
  messageInput.value =
    "Buongiorno Raphaël, grazie per averci contattato. Per circa 90 ospiti il prezzo è di €28.000 e include l'affitto della location, il catering e le bevande. Restiamo disponibili per organizzare una visita.";
  updateCount();
  venueInput.focus();
});

clearButton.addEventListener("click", () => {
  form.reset();
  updateCount();
  setView("empty");
  venueInput.focus();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  analyzeButton.disabled = true;
  analyzeButton.firstChild.textContent = "Analyzing… ";
  decisionError.hidden = true;

  const payload = {
    venue: venueInput.value.trim(),
    message: messageInput.value.trim(),
  };

  const threadId = threadInput.value.trim();
  if (threadId) payload.thread_id = threadId;

  try {
    const response = await fetch("/events/gmail", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || `Request failed with status ${response.status}`);
    }

    renderDecision(await response.json());
  } catch (error) {
    errorMessage.textContent = error instanceof Error ? error.message : "Try again.";
    setView("error");
  } finally {
    analyzeButton.disabled = false;
    analyzeButton.firstChild.textContent = "Analyze reply ";
  }
});

updateCount();
checkHealth();
