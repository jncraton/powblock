# powblock

Ephemeral proof-of-work public storage

## Create

POST:

  - uuid = ID for this block
  - content = block data, max_len=64k
  - hours = number of hours to store the data. integer between 1 and 720
  - pow = H(uuid + revision + content + nonce) < 2^256 / (base_cost * max(bytes,256) * hours)
  - nonce = 64bit integer found to pass pow
  - secret = cryptographically secure random number to use for future operations

Server stores `content` at `uuid` for `hours` if pow is correct. Revision is always `1` on creation. Server limits source IP addresses to one block creations per minute.

On creation, a hash of `secret` is stored with the block and use to authorize future operations.

```
POST /powblocks
Content-Type: application/json
Authorization: Bearer secret


{
  "uuid": "01J8Q2V6X7Y8Z9A0B1C2D3E4F5",
  "content": "This is the data stored in the block.",
  "hours": 24,
  "pow": "0000008f4a...",
  "nonce": 1844674407,
}

HTTP/1.1 201 Created
Content-Type: application/json
{
  "expires": 1787925546,
}
```
## Read

```
GET /powblocks/01J8Q2V6X7Y8Z9A0B1C2D3E4F5


HTTP/1.1 200 OK
{
  "revision": 1,
  "content": "This is the data stored in the block.",
}
```

## Update

```
PUT /powblocks/01J8Q2V6X7Y8Z9A0B1C2D3E4F5
Content-Type: application/json
Authorization: Bearer secret

{
  "content": "Updated data stored in the block.",
  "hours": 24,
  "revision": 2,
  "pow": "000000ef57...",
  "nonce": 1844674407,
}

HTTP/1.1 201 Created
```

`revision` must be greater than stored `revision` or update will fail.

## Delete

```
DELETE /powblocks/01J8Q2V6X7Y8Z9A0B1C2D3E4F5
Authorization: Bearer secret

HTTP/1.1 200 OK
```

## Vacuuming

- Block data is zeroed when it expires, but the UUID and secret are stored for use for 12*hours

## Data Model

Data is stored in single table with the following scheme:

```sql
create table powblocks (
  uuid text primary key
    collate binary
    check (length(uuid) = 26),

  revision integer not null default 1
    check (revision >= 1),

  content blob not null
    check (length(content) <= 65536),

  created_at integer not null,
  updated_at integer not null,
  expires_at integer not null,

  secret_hash blob not null
    check (length(secret_hash) = 32),
);
```
