# powblock

Ephemeral proof-of-work public storage

## Creating a block

POST:

  - uuid = ID for this block
  - content = block data, max_len=64k
  - hours = number of hours to store the data. integer between 1 and 720
  - pow = H(uuid + content + nonce) < 2^256 / (base_cost * min(bytes,256) * hours)
  - nonce = 64bit integer found to pass pow
  - modification_key = random key used for future modifications

Server stores `content` at `uuid` for `hours` if pow is correct. Server limits source IP addresses to one block creations per minute.

## Vacuuming

- Block data is zeroed when it expires, but the UUID and modification_key are stored for use for 12*hours
