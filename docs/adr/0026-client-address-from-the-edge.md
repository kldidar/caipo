# ADR-0026: The public instance takes the client address from the edge's header

- Status: Accepted
- Date: 2026-11-25; accepted by the project owner on 2026-11-25
- Supersedes: [ADR-0024](0024-public-demonstration-instance.md) point 7

## Context

ADR-0024 point 7 decided that, behind Render's proxy, the sign-in throttle and the record of a sign-in take the client address from `X-Forwarded-For`, counted from the right: the entry Render's own proxy adds, never one the client sent. Its check 2 before the link is given out measures the proxy's behaviour on the instance, with a forged header.

The measurement was made on Day 47 (2026-11-23), with the throttle as the oracle ([INSTANCE.md](../INSTANCE.md), the measurement):
- With one entry counted from the right, a forged entry was never read, but the entry read changed from request to request. It was one of several proxies' addresses, so all visitors shared a few sources.
- With two, the results fitted no fixed layout of the header. A run with a different forged entry on each request was never throttled, and a run with one constant forged entry was throttled at irregular points. The number of entries Render's proxies add is not fixed, or not known, so no count from the right is the client's address.

Render serves `onrender.com` through Cloudflare (`server: cloudflare` on every response). Cloudflare writes the address that connected to it into `CF-Connecting-IP`. Cloudflare documents that header as the client's address for the origin. On 2026-11-25 a request to the instance that carried a `CF-Connecting-IP` of its own was refused by Cloudflare itself (403, `server: cloudflare`, `error code: 1000`) and never reached the application, while the same request without it was answered. A Render user reported in 2024 that Render keeps an `X-Forwarded-For` the client sent and appends to it. A Render staff reply of 2021 said the first entry is the client's, but the first entry is the one a client can write.

## Decision

1. On the public instance, the client address for throttling and for the record of a sign-in is the value of `CF-Connecting-IP`. The header is named in the instance's settings (`CLIENT_ADDRESS_HEADER`), not in the environment.
2. If that header is missing, or holds anything but one IP address, the peer address is used. It may be a proxy's, shared by several visitors, but a client never chooses it.
3. `X-Forwarded-For` is not read anywhere. Every other environment reads no header, as before.
4. Before the link is given out, the measurement is made again: failed sign-ins with a different forged `X-Forwarded-For` on each, which pass only if the throttle refuses the 21st; and one request with a forged `CF-Connecting-IP`, which passes only if it is refused before the application.

## Alternatives considered

- **Keep counting from the right of `X-Forwarded-For`, with the count found from the stored source keys.** It depends on a number of hops that the Day 47 runs showed is not stable. A change at Render or Cloudflare would silently make it count a forged entry or a proxy's.
- **Use Cloudflare's `True-Client-IP`.** Cloudflare adds it only on its Enterprise plan; the plan Render uses is not ours to know.
- **The peer address only.** It cannot be forged, but behind the proxies it is shared by many visitors, so one visitor's failures would refuse others.

## Consequences

- The client address no longer depends on how many proxies append to `X-Forwarded-For`. The setting `CAIPO_TRUSTED_PROXY_COUNT` is gone; a value left in Render's settings is ignored.
- The instance trusts that every request reaches it through Cloudflare. If Render served the host without Cloudflare, a client could write `CF-Connecting-IP` itself and choose its source. The measurement in point 4 would show that, and the risk is recorded in [SECURITY.md](../../SECURITY.md).
- Nothing changes outside the instance.

## Revisit when

- responses from the instance no longer carry `server: cloudflare`, or Render documents another header for the client address;
- the research platform is deployed (ADR-0008), which decides its own proxy and client address.
