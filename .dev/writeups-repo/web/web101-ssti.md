---
challenge: "Web 101"
title: "SSTI via the name parameter"
author: "alice"
sort_order: 1
tags: [web, ssti, python]
language: en
visible: true
---

## Overview

This challenge exposes a Flask endpoint that passes user input directly to `render_template_string`.

## Exploitation

Send the following payload in the `name` query parameter:

<!--redact-->{{config.SECRET_KEY}}<!--/redact-->

This works because the template context includes the Flask config object.

## Flag

```flag
CTF{ssti_is_fun}
```

## Takeaways

Never pass user input to `render_template_string` without sanitization.
