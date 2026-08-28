# powblock

Ephemeral proof-of-work public storage

## Creating a block

POST:

  - uuid = ID for this block
  - content = block data
  - hours = number of hours to store the data (max 720)
  - pow = H(uuid + content + nonce) < 2^256 / (base_cost * bytes * hours)
  - nonce = 64bit integer found to pass pow
  - modification_key = random key used for future modifications

Server stores `content` at `uuid` for `hours` if pow is correct. Server limits source IP addresses to one block creations per minute.
