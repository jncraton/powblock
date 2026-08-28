# powblock

Ephemeral proof-of-work public storage

## Create

POST:

  - uuid = ID for this block
  - content = block data, max_len=64k
  - hours = number of hours to store the data. integer between 1 and 720
  - pow = H(uuid + content + nonce) < 2^256 / (base_cost * min(bytes,256) * hours)
  - nonce = 64bit integer found to pass pow
  - modification_key = random key used for future modifications

Server stores `content` at `uuid` for `hours` if pow is correct. Server limits source IP addresses to one block creations per minute.

```
POST /powblocks
Content-Type: application/json

{
  "uuid": "01J8Q2V6X7Y8Z9A0B1C2D3E4F5",
  "content": "This is the data stored in the block.",
  "hours": 24,
  "pow": "0000008f4a...",
  "nonce": 1844674407,
  "modification_key": "random-secret-key"
}
```
## Read

```
GET /blocks/01J8Q2V6X7Y8Z9A0B1C2D3E4F5
```

## Update

```
PUT /blocks/01J8Q2V6X7Y8Z9A0B1C2D3E4F5
Content-Type: application/json

{
  "content": "Updated data stored in the block.",
  "hours": 24,
  "pow": "000000ef57...",
  "nonce": 1844674407,
  "modification_key": "random-secret-key"
}
```

## Delete

```
DELETE /blocks/01J8Q2V6X7Y8Z9A0B1C2D3E4F5
Content-Type: application/json

{
  "modification_key": "random-secret-key"
}
```


## Vacuuming

- Block data is zeroed when it expires, but the UUID and modification_key are stored for use for 12*hours
