---
challenge: "Web 101"
title: "Alternative approach: cookie tampering"
author: "bob"
sort_order: 2
tags: [web]
---

## Another way in

You can also solve this without SSTI at all.

The session cookie is signed with a weak key. Brute-force it with flask-unsign:

```spoiler
flask-unsign --unsign --cookie "eyJ1c2VyIjoiZ3Vlc3QifQ..." --wordlist rockyou.txt
```

Then forge an admin session and read the flag from the dashboard.
