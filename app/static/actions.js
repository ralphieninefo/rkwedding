/* Shared venue actions: previewed inquiry, reply, reminder, and decisions.
 * Every send opens a dialog showing the exact mailbox, recipient, subject,
 * and body, and only the confirm button sends. Pages call
 * window.VenueActions.install({onChange, onMessage}).
 */
(() => {
  const DIALOGS = `
    <dialog class="dialog" id="outreachDialog" aria-labelledby="outreachDialogTitle">
      <div class="dialog-heading">
        <div><p class="eyebrow">Review before sending</p><h2 id="outreachDialogTitle">Venue inquiry</h2></div>
        <button class="dialog-close" type="button" data-close="outreachDialog" aria-label="Close">×</button>
      </div>
      <div class="fields">
        <p class="from-line" id="outreachFrom"></p>
        <label><span>To</span><input id="outreachRecipient" type="text" readonly></label>
        <label><span>Subject</span><input id="outreachSubject" type="text" readonly></label>
        <label><span>Message</span><textarea id="outreachBody" readonly></textarea></label>
      </div>
      <p class="message" id="outreachDialogMessage" role="status"></p>
      <div class="dialog-actions">
        <button class="button button-secondary" type="button" data-close="outreachDialog">Cancel</button>
        <button class="button button-primary" id="confirmOutreach" type="button">Send inquiry</button>
      </div>
    </dialog>
    <dialog class="dialog" id="followupDialog" aria-labelledby="followupDialogTitle">
      <div class="dialog-heading">
        <div><p class="eyebrow">Review before sending</p><h2 id="followupDialogTitle">Reply to venue</h2></div>
        <button class="dialog-close" type="button" data-close="followupDialog" aria-label="Close">×</button>
      </div>
      <div class="context-box">
        <span>Their latest reply, in short</span>
        <strong id="followupSummary"></strong>
      </div>
      <div class="fields">
        <p class="from-line" id="followupFrom"></p>
        <label><span>To</span><input id="followupRecipient" type="text" readonly></label>
        <label><span>Subject</span><input id="followupSubject" type="text" readonly></label>
        <div class="draft-helper">
          <label><span>Say it in English, get an Italian draft</span><textarea id="draftPoints" rows="3" placeholder="e.g. Thank them, ask if 2 October is free, ask what the menu price includes."></textarea></label>
          <button class="button button-secondary button-small" id="draftButton" type="button">Draft in Italian</button>
        </div>
        <label><span>Your reply (Italian)</span><textarea id="followupBody"></textarea></label>
      </div>
      <p class="message" id="followupDialogMessage" role="status"></p>
      <div class="dialog-actions">
        <button class="button button-secondary" type="button" data-close="followupDialog">Cancel</button>
        <button class="button button-primary" id="confirmFollowup" type="button">Send reply</button>
      </div>
    </dialog>
    <dialog class="dialog" id="reminderDialog" aria-labelledby="reminderDialogTitle">
      <div class="dialog-heading">
        <div><p class="eyebrow">Review before sending</p><h2 id="reminderDialogTitle">Send a reminder</h2></div>
        <button class="dialog-close" type="button" data-close="reminderDialog" aria-label="Close">×</button>
      </div>
      <div class="fields">
        <p class="from-line" id="reminderFrom"></p>
        <label><span>To</span><input id="reminderRecipient" type="text" readonly></label>
        <label><span>Subject</span><input id="reminderSubject" type="text" readonly></label>
        <label><span>Message (Italian, editable)</span><textarea id="reminderBody"></textarea></label>
      </div>
      <p class="message" id="reminderDialogMessage" role="status"></p>
      <div class="dialog-actions">
        <button class="button button-secondary" type="button" data-close="reminderDialog">Cancel</button>
        <button class="button button-primary" id="confirmReminder" type="button">Send reminder</button>
      </div>
    </dialog>`;

  const readApiResponse = async (response) => {
    const text = await response.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch {
      throw new Error(response.ok
        ? "The server returned an unreadable response. Please refresh and try again."
        : `The request failed (${response.status}). Please refresh and try again.`);
    }
  };

  const api = async (path, options = {}) => {
    const response = await fetch(path, options);
    const result = await readApiResponse(response);
    if (!response.ok) throw new Error(result.detail || "Something went wrong. Please try again.");
    return result;
  };

  const withBusy = async (button, busyText, work) => {
    if (!button) return work();
    const original = button.textContent;
    button.disabled = true;
    button.textContent = busyText;
    try {
      return await work();
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  };

  const mailboxLine = (target, email, verb) => {
    target.textContent = email ? `${verb} ` : "";
    if (email) {
      const bold = document.createElement("b");
      bold.textContent = email;
      target.append(bold);
    }
  };

  const install = ({onChange, onMessage, primaryMailbox}) => {
    const host = document.createElement("div");
    host.innerHTML = DIALOGS;
    document.body.append(...host.children);
    const $ = (selector) => document.querySelector(selector);
    document.querySelectorAll("[data-close]").forEach((button) => {
      button.addEventListener("click", () => document.getElementById(button.dataset.close).close());
    });
    const message = (text, tone) => onMessage?.(text, tone);
    const changed = async () => { if (onChange) await onChange(); };
    let pendingVenue = null;

    const outreachDialog = $("#outreachDialog");
    const confirmOutreach = $("#confirmOutreach");
    const openOutreachPreview = (venue, button) => withBusy(button, "Loading…", async () => {
      try {
        const preview = await api(`/api/venues/${venue.id}/outreach-preview`);
        pendingVenue = venue;
        mailboxLine($("#outreachFrom"), typeof primaryMailbox === "function" ? primaryMailbox() : primaryMailbox, "Sent from");
        $("#outreachRecipient").value = preview.recipient;
        $("#outreachSubject").value = preview.subject;
        $("#outreachBody").value = preview.body;
        $("#outreachDialogMessage").textContent = "";
        confirmOutreach.disabled = false;
        confirmOutreach.textContent = "Send inquiry";
        outreachDialog.showModal();
      } catch (error) {
        message(error.message, "error");
      }
    });
    confirmOutreach.addEventListener("click", async () => {
      if (!pendingVenue) return;
      const venue = pendingVenue;
      confirmOutreach.disabled = true;
      confirmOutreach.textContent = "Sending…";
      $("#outreachDialogMessage").textContent = "Sending through Gmail…";
      try {
        const result = await api(`/api/venues/${venue.id}/send`, {method: "POST"});
        outreachDialog.close();
        if (result.sent) {
          message(`Inquiry sent to ${venue.name}.`, "success");
        } else if (result.existing_in?.length) {
          message(`Not sent: ${result.existing_in.join(" and ")} already has a conversation with ${venue.name}. It will be attached on the next Gmail check.`, "error");
        } else {
          message(`Not sent: ${venue.name} already has correspondence.`, "error");
        }
        await changed();
      } catch (error) {
        $("#outreachDialogMessage").textContent = error.message;
        confirmOutreach.disabled = false;
        confirmOutreach.textContent = "Send inquiry";
      }
    });

    const followupDialog = $("#followupDialog");
    const confirmFollowup = $("#confirmFollowup");
    const followupBody = $("#followupBody");
    const draftPoints = $("#draftPoints");
    const draftButton = $("#draftButton");
    const openFollowupPreview = (venue, button) => withBusy(button, "Loading…", async () => {
      try {
        const preview = await api(`/api/venues/${venue.id}/followup-preview`);
        pendingVenue = venue;
        $("#followupSummary").textContent = preview.response_summary || "Response received.";
        mailboxLine($("#followupFrom"), preview.gmail_account_email, "Reply goes from");
        $("#followupRecipient").value = preview.recipient;
        $("#followupSubject").value = preview.subject;
        followupBody.value = preview.body;
        draftPoints.value = "";
        $("#followupDialogMessage").textContent = "";
        confirmFollowup.disabled = false;
        confirmFollowup.textContent = "Send reply";
        followupDialog.showModal();
      } catch (error) {
        message(error.message, "error");
      }
    });
    draftButton.addEventListener("click", async () => {
      if (!pendingVenue || !draftPoints.value.trim()) {
        $("#followupDialogMessage").textContent = "Write a few English points first.";
        return;
      }
      await withBusy(draftButton, "Drafting…", async () => {
        try {
          const result = await api(`/api/venues/${pendingVenue.id}/draft-reply`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({points: draftPoints.value.trim()}),
          });
          followupBody.value = result.body;
          $("#followupDialogMessage").textContent = "Draft ready — read it, edit anything, then send.";
        } catch (error) {
          $("#followupDialogMessage").textContent = error.message;
        }
      });
    });
    confirmFollowup.addEventListener("click", async () => {
      if (!pendingVenue || !followupBody.value.trim()) return;
      const venue = pendingVenue;
      confirmFollowup.disabled = true;
      confirmFollowup.textContent = "Sending…";
      $("#followupDialogMessage").textContent = "Sending in the existing Gmail thread…";
      try {
        await api(`/api/venues/${venue.id}/reply`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({body: followupBody.value.trim()}),
        });
        followupDialog.close();
        message(`Reply sent to ${venue.name}.`, "success");
        await changed();
      } catch (error) {
        $("#followupDialogMessage").textContent = error.message;
        confirmFollowup.disabled = false;
        confirmFollowup.textContent = "Send reply";
      }
    });

    const reminderDialog = $("#reminderDialog");
    const confirmReminder = $("#confirmReminder");
    const reminderBody = $("#reminderBody");
    const openReminderPreview = (venue, button) => withBusy(button, "Loading…", async () => {
      try {
        const preview = await api(`/api/venues/${venue.id}/reminder-preview`);
        pendingVenue = venue;
        mailboxLine($("#reminderFrom"), preview.gmail_account_email, "Sent from");
        $("#reminderRecipient").value = preview.recipient;
        $("#reminderSubject").value = preview.subject;
        reminderBody.value = preview.body;
        $("#reminderDialogMessage").textContent = "";
        confirmReminder.disabled = false;
        confirmReminder.textContent = "Send reminder";
        reminderDialog.showModal();
      } catch (error) {
        message(error.message, "error");
      }
    });
    confirmReminder.addEventListener("click", async () => {
      if (!pendingVenue || !reminderBody.value.trim()) return;
      const venue = pendingVenue;
      confirmReminder.disabled = true;
      confirmReminder.textContent = "Sending…";
      $("#reminderDialogMessage").textContent = "Sending in the existing Gmail thread…";
      try {
        await api(`/api/venues/${venue.id}/remind`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({body: reminderBody.value.trim()}),
        });
        reminderDialog.close();
        message(`Reminder sent to ${venue.name}.`, "success");
        await changed();
      } catch (error) {
        $("#reminderDialogMessage").textContent = error.message;
        confirmReminder.disabled = false;
        confirmReminder.textContent = "Send reminder";
      }
    });

    const setDecision = (venue, decision, button) => withBusy(button, "Saving…", async () => {
      try {
        await api(`/api/venues/${venue.id}`, {
          method: "PATCH",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({decision}),
        });
        message(
          decision === "passed" ? `${venue.name} moved to Closed.`
            : decision === "shortlisted" ? `${venue.name} added to the shortlist.`
              : `${venue.name} is back in the running.`,
          "success",
        );
        await changed();
      } catch (error) {
        message(error.message, "error");
      }
    });

    return {api, withBusy, openOutreachPreview, openFollowupPreview, openReminderPreview, setDecision};
  };

  window.VenueActions = {install, api, withBusy};
})();
