---
challenge: "Heap Feng Shui"
title: "Grooming the heap for fun and profit"
author: "carol"
tags: [pwn, heap]
---

## Setup

The binary has a UAF in the `delete_note` handler.

## Exploit

Groom the heap so the freed chunk overlaps a tcache entry, then overwrite the
fd pointer to point at `__free_hook`:

<!--redact-->The exact offset is 0x290 — allocate 5 notes of size 0x80 first.<!--/redact-->

## Flag

```flag
CTF{heap_master_2026}
```
