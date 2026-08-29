# Gmail Push Setup

## What Gmail sends

Gmail push notifications do not include an email body. A notification contains:

```json
{
  "emailAddress": "mailbox@example.com",
  "historyId": "9876543210"
}
```

The application must persist the prior history ID, call Gmail `users.history.list`, identify added messages, and fetch the complete thread before asking the model to reason about a reply.

## Google Cloud setup checklist

1. Create or select a Google Cloud project.
2. Enable the Gmail API and Cloud Pub/Sub API.
3. Configure the OAuth consent screen.
4. Create OAuth credentials for the wedding mailbox workflow.
5. Create a Pub/Sub topic in the same project used to call Gmail `users.watch`.
6. Grant `gmail-api-push@system.gserviceaccount.com` permission to publish to the topic.
7. Create a push subscription whose endpoint is the deployed App Platform URL:

   ```text
   https://<app-host>/events/gmail/push?token=<shared-verification-token>
   ```

8. Call Gmail `users.watch` with the fully qualified topic name:

   ```text
   projects/<google-project-id>/topics/<topic-name>
   ```

9. Store the returned starting `historyId` in durable state.
10. Renew the Gmail watch before its returned expiration time. A scheduled daily renewal is the intended production approach.

## Next code slice

The current repository verifies and decodes the push envelope. The next code slice should add:

- Google OAuth credential loading and refresh;
- a durable per-mailbox history ID store;
- `users.history.list` pagination;
- complete Gmail thread retrieval and MIME text extraction;
- duplicate-event protection;
- normalization into `GmailEvent`;
- Sheet lookup before inference;
- draft creation after a validated decision and human-approval check.

Do not acknowledge a notification as fully processed until the durable history ID advances successfully. Do not use an in-memory background task as the only production processing mechanism.
