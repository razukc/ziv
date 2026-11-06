# cJSON (vendored)

[cJSON](https://github.com/DaveGamble/cJSON) v1.7.18, MIT licence (see
`LICENSE`), vendored unmodified: `cJSON.c` and `cJSON.h` only. Used by the
band's utterance decoder and transport (`firmware/band/`) on the host.
ESP-IDF ships the same library as its `json` component, so the device build
links that one and this copy is for host builds only.

| File | Upstream sha256 |
|---|---|
| `cJSON.c` | `75c51de8fa40ac9d7a99319c6330719bd692eb81c0a869265f3d4c682533f9b9` |
| `cJSON.h` | `0578cc29132912edbc88f83207a8fc76e5db3db0605497e909a9384ef3cc474b` |
| `LICENSE` | `a36dda207c36db5818729c54e7ad4e8b0c6fba847491ba64f372c1a2037b6d5c` |

Compiles clean under the repo's `-std=c11 -Wall -Wextra -Werror`.
