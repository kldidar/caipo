# Deployment options for CAIPO (I1, B17, ADR-0008)

Status: Comparison and recommendation · 2026-11-11 · **Decides nothing.** [ADR-0008](../adr/0008-deployment-strategy.md) stays Proposed, and blocker B17 stays open, until the project owner accepts or changes the recommendation below.

The owner asked on 2026-11-05 for a comparison of where and how CAIPO could be put online:
- hosting abroad or in Uzbekistan;
- price;
- the email service;
- the domain;
- the legal requirements on where personal data are stored.

Prices and terms were read from the providers' own pages and the law's official text on 2026-11-11 unless marked otherwise. Prices change; each is to be checked again on the day of purchase.

## Summary

- **The law allows a server abroad for what CAIPO holds.** Since Law ZRU-1125 of 26 March 2026, Article 27¹ of the Law "On personal data" requires storage in Uzbekistan only for:
  - biometric and genetic data;
  - data of users of telecom operators working in Uzbekistan.

  CAIPO holds none of these. Other personal data may be stored abroad in a country recognised as giving adequate protection. The list of 29 July 2026 names Germany. Obligations that remain are listed in §2; a lawyer should confirm them before real users register (Q-8: "lawyer later").
- **Recommended:**
  - a Hetzner Cloud server in Germany, **CPX22** (2 vCPU, 4 GB, 80 GB), **€19.99 a month** before VAT;
  - Hetzner's daily backups, **about €1.10 a month**;
  - a free transactional email plan (Brevo, 300 messages a day, a French company);
  - a domain the owner registers.

  About **€21 to €25 a month** in all, plus the domain.
- **The local alternative** is Pro-Data in Tashkent: **Generic 4** (4 vCPU, 4 GB, 100 GB), **$59 a month**. It needs no legal assessment of storage abroad, and it is fast for users in Uzbekistan through TAS-IX. It costs about three times as much, and its backups are priced separately.
- **What is deployed first** is Phase 1 and the demonstrator: the web application, PostgreSQL, and a reverse proxy. The isolated workers of ADR-0011 come with Phase 2, on the same server, when its gate is READY.

## 1. What has to run

| Component | First deployment | Phase 2 and later |
|---|---|---|
| Reverse proxy with TLS | Caddy, with automatic Let's Encrypt certificates | Same |
| Web application | Django behind a WSGI server, from one image built in CI | Same |
| PostgreSQL 18 | On the same server, in its own container, not exposed | Same, with pgvector when ADR-0003 is accepted |
| Redis | Not needed: nothing in the application uses it yet | The isolated workers' queues (ADR-0004, ADR-0011) |
| Workers, egress proxy | Not deployed | Fetch, parse, and trusted workers; the egress proxy (ADR-0011) |
| Email | An SMTP relay, through Django's built-in SMTP backend (no new library) | Same |

2 vCPU and 4 GB of memory hold the first deployment with room to spare. The full test suite runs in CI on a runner of that size. Phase 5 (embeddings) may need more memory, which ADR-0006 decides; the server can be resized.

## 2. The law on where personal data are stored

**What CAIPO holds about a person:**
- an email address;
- a password hash;
- an encrypted second-factor secret;
- the times and keyed hashes of sign-in attempts;
- the records of what the account did.

It holds no biometric or genetic data, and CAIPO is not a telecom operator.

**Article 27¹ as amended by ZRU-1125** (signed 26 March 2026, in force from its publication on 27 March 2026), read on lex.uz:

1. Must be stored in Uzbekistan: biometric data, genetic data, and data of individuals who use the services of telecom operators active in Uzbekistan.
2. Other personal data may be stored and processed abroad if one of these holds:
   - the foreign state is recognised as giving adequate protection (the Cabinet of Ministers keeps the list);
   - the operator follows standard contractual terms or binding corporate rules approved by the authorised body;
   - the operator follows international standards on a list that body approves.
3. Registration in the State Register applies to databases that must be stored locally (Article 20). CAIPO's would not be one.

**The adequacy list.** Cabinet of Ministers Resolution No. 415 of 29 July 2026 (in force 3 August 2026) lists 49 countries and territories. A legal summary names Germany, France, and the Netherlands among them, and the EU member states generally. The United States is listed only for companies under the EU–US data privacy framework. The full list was not read from the official text, so Germany is recommended over Finland, which the summary does not name.

**What stays to be done, whichever host is chosen**, for a lawyer to confirm:
- A privacy notice at registration and account creation. Article 23 requires telling a person in writing when their data enter a database, and Article 22 about any transfer abroad.
- Article 15 on cross-border transfer, and how it combines with Article 27¹.
- A security-incident procedure: incidents involving data stored abroad are reported to the authorised body within 24 hours, with a full report within 72 hours (per the legal summary; to be checked against the resolution).
- The email service is a second processor abroad (§4): it receives each recipient's address.

## 3. Servers compared

| | Hetzner Cloud, Germany (recommended) | Hetzner Cloud, Finland | Pro-Data, Tashkent |
|---|---|---|---|
| Plan | CPX22 (Regular Performance) | CPX22 | Generic 4 |
| vCPU / memory / disk | 2 / 4 GB / 80 GB NVMe | 2 / 4 GB / 80 GB NVMe | 4 / 4 GB / 100 GB SSD |
| Price a month | €19.99 (Nuremberg), before VAT; IPv4 included | €16.99 (Helsinki), before VAT | $59, "approximate" per the provider |
| Traffic | 20 TB | 20 TB | 100 Mbit/s to the internet and TAS-IX |
| Backups | €1.098 a month, 7 daily slots | Same | Offered, priced separately (not shown) |
| Storage abroad allowed for CAIPO's data | Yes: Germany is on the list | Probably: Finland is an EU member, but not named in the summary read | Not applicable: stored in Uzbekistan |
| Latency for users in Uzbekistan | Higher than local; adequate for a server-rendered site | Same | Lowest; TAS-IX |
| Note | The page showed creation of these plans as "currently unavailable" on 2026-11-11; the cheaper Cost-Optimized line, from €5.99, was also listed. Check on the day | Same | Local support in Uzbekistan |

**Not compared in detail:** aHost.uz (VDS Cloud 150 at 395,000 UZS a month, per a listing site, own data center on TAS-IX), Serverspace Tashkent, DigitalOcean, OVH. Hetzner's prices rose in June 2026 (reported by several sites); the figures above are the current ones from its own page.

## 4. Email

CAIPO sends few messages: account verification, password reset, and recovery notices. Django's SMTP backend sends them; no library is added.

| Service | Price for CAIPO's volume | Where | Note |
|---|---|---|---|
| **Brevo** (recommended) | Free: 300 messages a day, with transactional SMTP (per several reviews; the official page did not load) | A French company (France is on the adequacy list) | Sending starts after Brevo approves the account; needs the domain's SPF and DKIM records |
| Amazon SES | $0.10 per 1,000 messages à la carte; up to $200 of free-tier credit for a new AWS account | AWS regions; the EU ones to be confirmed | An AWS account, and leaving SES's sandbox, are needed |
| Mailgun, Postmark | About $15 a month (Mailgun Basic); Postmark's free tier is 100 a month (per reviews) | Mailgun has an EU region; Postmark is in the US | More than CAIPO needs |

**The email service sees only an address and the message.** The messages hold one link and no personal data beyond the recipient's address (SECURITY.md, "Email").

## 5. Domain

A domain is needed for TLS and for the email service's SPF and DKIM records.

| Option | Price a year | Note |
|---|---|---|
| A `.uz` name | About $28 and up at international registrars, more at many (per a price-comparison site); local registrars price in sums | Signals the study's place. Foreign organisations need a presence in Uzbekistan; the owner, as a resident, does not |
| A `.org` or `.com` name | Usually about $10 to $15 (not checked for a specific registrar) | Neutral; widely trusted |

Which name, and where to register it, is the owner's choice. Its availability was not checked.

## 6. Backups

ADR-0008 requires backups encrypted before they leave the server, kept elsewhere, with a scheduled restore test.
- **Hetzner's server backups** (€1.098 a month) cover a failed server, but they are copies of the whole disk held by the same provider.
- **Encrypted dumps of the database** are therefore also sent off the server, for example `pg_dump` encrypted with `age` or `restic`, to a storage service in another location; its price was not checked.
- **A restore test** is part of the deployment Day.

## 7. Recommendation, for the owner to accept or change

1. **Server:** Hetzner Cloud CPX22 in Germany (Nuremberg or Falkenstein), €19.99 a month. If creation is unavailable on the day, the nearest available plan with at least 2 vCPU and 4 GB, in Germany. Alternative: Pro-Data Generic 4 in Tashkent, if keeping the data in Uzbekistan matters more than the price.
2. **Email:** Brevo's free plan, sending from the project's domain.
3. **Domain:** one the owner chooses and registers in their own name.
4. **Shape:** as ADR-0008 proposes. That means one image built in CI and Docker Compose on one server. Caddy handles TLS, and migrations run as an explicit step. Backups are encrypted, kept off the server, and restore-tested. The first deployment has no workers and no Redis.
5. **Before real users register:** the privacy notice and the incident procedure of §2, checked by a lawyer.

**The owner's part.** These are purchases and accounts in the owner's name, which Claude Code cannot make:
- the server;
- the domain;
- the email account.

Then Claude Code writes the deployment configuration and instructions in a Day of its own. The CI image build needs the owner's approval as a change of CI.

## Sources

- Law "On personal data" (ZRU-547), Article 27¹ as amended by ZRU-1125: [lex.uz/ru/docs/4396428](https://lex.uz/ru/docs/4396428); news: [Kun.uz, 2026-03-28](https://kun.uz/ru/news/2026/03/28/xraneniye-nekotoryx-personalnyx-dannyx-za-predelami-uzbekistana-razresheno), [Dentons, 2026-03-31](https://www.dentons.com/en/insights/articles/2026/march/31/uzbekistan-dismantles-strict-data-localization-regime)
- Resolution No. 415 of 29 July 2026, summary: [Settle Advisory](https://settleadvisory.com/news-en/uzbekistan-approves-list-of-countries-providing-an-adequate-level-of-personal-data-protection/)
- Hetzner Cloud prices: [hetzner.com/cloud/regular-performance](https://www.hetzner.com/cloud/regular-performance/), [hetzner.com/cloud](https://www.hetzner.com/cloud/)
- Pro-Data: [pro-data.tech/en/virtual-server](https://www.pro-data.tech/en/virtual-server); aHost: [listing](https://www.whtop.com/plans/ahost.uz/142323)
- Amazon SES: [aws.amazon.com/ses/pricing](https://aws.amazon.com/ses/pricing/); Brevo: reviews such as [sender.net](https://www.sender.net/reviews/brevo/pricing/free-plan)
- `.uz` prices: [domainoffer.net](https://domainoffer.net/price-compare-uz)
