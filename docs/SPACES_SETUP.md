# Private Gmail attachment storage

The application uses one private DigitalOcean Spaces bucket for every venue.
Venue separation is logical: object keys begin with the stable PostgreSQL venue
ID rather than creating a bucket for each venue.

## 1. Create the bucket

1. Use the existing `rkwedding` Spaces bucket in `sfo2`:
   `https://rkwedding.sfo2.digitaloceanspaces.com`.
2. Keep the bucket and its files private.
3. Do not enable the CDN; documents are opened through short-lived signed URLs.

## 2. Create the application key

Create a dedicated Spaces access key with read/write/delete permission limited
to this bucket. Do not reuse a personal or full-account key.

## 3. Configure both App Platform components

Add the following variables to both the `web` service and the `gmail-sync`
scheduled job:

```text
SPACES_BUCKET=rkwedding
SPACES_REGION=sfo2
SPACES_ACCESS_KEY_ID=<encrypted key ID>
SPACES_SECRET_ACCESS_KEY=<encrypted secret>
```

`SPACES_ENDPOINT_URL` is optional. When omitted, the application derives
`https://{SPACES_REGION}.digitaloceanspaces.com`.

The scheduled worker requires write access to mirror Gmail attachments. The web
service requires read access to generate ten-minute private viewing links.

## 4. Deploy and verify

After deployment:

1. Confirm `/health` reports `document_storage: configured`.
2. Allow the next `gmail-sync` run to complete, or run the existing private sync
   action once.
3. Open `/venues` and locate a venue with an attached quote.
4. Confirm its **Documents** section shows the file.
5. Confirm **View** opens the private file and **Open in Gmail** opens the source
   conversation.

The first synchronization also checks attachments on already-known Gmail
messages, so recent documents are backfilled rather than limited to new mail.

## Object layout

```text
venues/{venue_id}/messages/{gmail_message_id}/attachments/
  {gmail_attachment_id}/{sanitized_filename}
```

PostgreSQL stores the object key, checksum, type, size, Gmail source IDs, and
message relationship. The browser never receives the object key or the Spaces
credentials.
