# HTMX

Served by this application, at a pinned version, so that no page loads a script
from a third party (ADR-0010 point 10).

| File | Package | Licence |
|---|---|---|
| `htmx.min.js` | `htmx.org` 2.0.11, `dist/htmx.min.js`, unchanged | Zero-Clause BSD (`LICENSE.txt`) |

Obtained on 2026-11-20 from `registry.npmjs.org/htmx.org/-/htmx.org-2.0.11.tgz`,
whose SHA-512 matched the registry's integrity value. SHA-256 of `htmx.min.js`:
`d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717`.

The pages that load it configure it in their `htmx-config` meta element:
no evaluation of script from attributes or responses, no inline indicator
styles, requests only to this site, and no history cache.
