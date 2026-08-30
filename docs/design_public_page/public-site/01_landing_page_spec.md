# NSR MIS Public Landing Page: Design Spec

**Version** 0.1 · **Date** 29 August 2026 · **Owner** NSR MIS Architecture Team
**Status** Draft for MGLSD review. Content is placeholder throughout.
**Reference sites reviewed** GNHR Ghana (gnhr.mogcsp.gov.gh), existing Uganda Single Registry v2.0 (nsr.mglsd.go.ug)

---

## 0. How to read this document

This is the structure contract for the NSR MIS public landing page. It defines sections, components, data sources, and gates. It does not define final copy. Every string marked `{{slot}}` waits for approved MGLSD wording.

The `/design/README.md` currently says the design folder is not for marketing pages. That rule was written for the operator console handoff. The public site is a distinct surface with its own audience and its own compliance baseline, so it lives in `/design/public-site/` and does not touch the immutable `v0.1/` console folder. It does import `v0.1/tokens.css`.

Related documents:

| Doc | Why it matters here |
|---|---|
| `/docs/01_solution_architecture.docx` §3.3, §4.5, §4.7, §8, §11 | Channel model, API-DRS, GRM, DPPA controls, release phasing |
| `/docs/04_ui_design_brief.md` §4, §8 | Tokens and status vocabulary |
| `/design/v0.1/tokens.css` | Colour, type, spacing variables. Binding. |
| GOU Guidelines for Development and Management of Government Websites (2014) | Mandatory government web requirements |

---

## 1. Purpose and audiences

The NSR MIS public landing page is the front door to Uganda's National Social Registry. It does three jobs: explain what the registry is, publish what the registry knows in aggregate, and route four groups of people to the service each one needs.

| Audience | What they came for | Where the page sends them |
|---|---|---|
| Households and citizens | "Am I registered? How do I complain or correct my record?" | Check status, Lodge a grievance |
| Partner MDAs, programmes, researchers, donors | Registry data under a DSA | Request data (API-DRS) |
| Policy makers, media, general public | Coverage and poverty numbers | Statistics |
| Developers at partner MDAs | API contracts | Developer portal |

**Non-goals for v1.** No login to the operator console from this page. No personal data on any public URL. No household search. No payment or enrolment functions. No news blog until MGLSD names a content owner.

---

## 2. What we take from GNHR, and what we do differently

GNHR is the closest peer. Their homepage runs: hero with live counters, about, registry statistics with maps and tables, six-step process, data access, news, partners, helpline, footer.

**Take:**

- Live counters in the hero. Numbers first, prose second. Strong trust signal for a registry.
- A single dominant call to action in the header (`Data Request`) rather than five competing ones.
- The three-step data request explainer with a stated turnaround time. Sets expectations and cuts email traffic.
- Coverage distribution as a horizontal bar chart by tier. Readable without a legend.
- A named helpline band above the footer.
- A partner logo strip. Cheap credibility.

**Do differently:**

| GNHR does | NSR MIS should | Why |
|---|---|---|
| Publishes district-level poverty percentages in a public table | Apply a disclosure floor before publishing anything below sub-region | DPPA 2019 and re-identification risk in small parishes |
| Offers a helpline only, no online grievance | Full public GRM intake with a tracking code | GRM is an MVP module (US-085 onward). Use it. |
| No status check for households | Read-only status check, reference code plus OTP | SAD Release 1 includes a read-only status check |
| Hero counters animate on every load | Animate once, respect `prefers-reduced-motion` | WCAG 2.2.2 and low-bandwidth users |
| Interactive Leaflet map on the homepage | Static SVG choropleth on the homepage, interactive map on `/statistics` | The GNHR map fails when the tile API key is missing. A 400KB map library on a 3G connection is the wrong homepage trade. |
| Serif and mixed type scales | One type scale from `tokens.css` | Console and public site should feel like one system |

**Learn from the incumbent.** `nsr.mglsd.go.ug` already runs "The Single Registry for Social Protection Version 2.0" with the nav HOME / ABOUT / OVERVIEW / APPLICANTS / PAYMENTS / COMPLAINTS / EXITS / REPORTS / PUBLICATIONS. It carries the Coat of Arms, a flag stripe, a red wordmark, and a yellow footer band. Two questions that need answering before build, not after:

1. Does the NSR MIS public site replace that site, or sit beside it on a new subdomain?
2. Do the incumbent's APPLICANTS / PAYMENTS / EXITS sections migrate, get retired, or stay with the Single Registry?

Logged as LP-O-01 and LP-O-02.

---

## 3. Compliance baseline

Non-negotiable. Each item is an acceptance gate in §14.

**GOU website standards (2014).**

- Domain must be `.go.ug`. Proposed: `nsr.mglsd.go.ug` if we replace the incumbent, otherwise a new subdomain agreed with NITA-U.
- Banner carries the Uganda Coat of Arms, the ministry name, and the NSR logo.
- Ownership line in the header or footer: "This website belongs to the National Social Registry Unit, Ministry of Gender, Labour and Social Development."
- Mandatory sections: About, public services, publications, contact, search, sitemap, FAQ, feedback.
- Footer carries created date, last-updated date, Contact Us, privacy statement, disclaimer.
- No blinking or scrolling text. Kills the auto-advancing carousel on the incumbent site.
- English is the baseline. Any local-language page needs an English equivalent.

**Accessibility.** WCAG 2.1 AA. Full gates in §11.

**DPPA 2019.**

- No personal data on a public URL, in any state, ever.
- Every public statistic passes the disclosure floor in §8.3.
- The privacy notice is linked from every form on the page, not only from the footer.
- The DPO signs off the statistics set and the status-check design before launch.

---

## 4. Branding and token additions

### 4.1 Identity stack

Three layers, top to bottom:

1. **Government identity strip.** Full-bleed, 4px, split black / yellow / red left to right. Uganda flag reference. Decorative only, `aria-hidden="true"`.
2. **Government banner.** Coat of Arms at 48px, "Republic of Uganda · Ministry of Gender, Labour and Social Development" in caption size, contact email right-aligned. Background `--neutral-100`.
3. **Site header.** NSR wordmark, primary nav, one filled CTA. Sticky on scroll, height `--layout-topbar`.

Rationale: the government identity reads first, the service identity reads second. Same pattern the incumbent uses, cleaner execution.

### 4.2 Token additions required

`tokens.css` has no government identity colours and no public-site surfaces. Add a `public-site` block. Do not hardcode these anywhere else.

```css
/* ----- Government identity (public site only) ----- */
--gov-black:  #000000;
--gov-yellow: #FCDC04;
--gov-red:    #D90000;

/* ----- Public site surfaces ----- */
--public-hero-bg:      var(--primary-900);      /* #1F3864 */
--public-hero-bg-deep: #172B4D;                 /* gradient stop */
--public-hero-fg:      var(--neutral-0);
--public-accent:       #C8912A;                 /* CTA on dark, warm gold */
--public-accent-fg:    #1A1A1A;
--public-surface-alt:  #F7F9FC;                 /* alternating band */
--public-band-helpline:#FFF8E7;

/* ----- Public site layout ----- */
--public-content-max:  1200px;
--public-section-y:    var(--space-10);
```

**Colour ratio check, done (WCAG 1.4.3).** Measured, not estimated:

| Pair | Ratio | Verdict |
|---|---|---|
| `--public-accent` #C8912A on `--public-hero-bg` #1F3864 | 4.17:1 | Passes for large text and UI components (3:1). **Fails for body text (4.5:1).** Use it only at hero and section-heading size, and for button fills and borders. |
| `--public-accent-fg` #1A1A1A on `--public-accent` #C8912A | 6.25:1 | Passes AA everywhere. This is the CTA button pair. |
| `--neutral-0` on `--public-hero-bg` #1F3864 | 11.62:1 | Passes AAA. All hero body text uses this. |
| `--neutral-700` #444444 on `--public-surface-alt` #F7F9FC | 9.23:1 | Passes AAA |
| `--gov-yellow` #FCDC04 on `--gov-black` #000000 | 15.38:1 | Passes AAA. The only permitted use of the yellow with text. |

**Do not** use `--gov-yellow` as a background for text. #FCDC04 against black is fine, against white it fails. It appears only as a 4px strip and as a 2px underline on the active nav item.

### 4.3 Typography

Inter throughout, from `--font-primary`. The public site adds two display steps above the console scale, because a landing hero at 24px looks like an error.

```css
--fs-hero:    clamp(32px, 5vw, 56px);  --lh-hero:    1.1;
--fs-section: clamp(24px, 3vw, 36px);  --lh-section: 1.2;
```

Everything below section headings uses the existing scale unchanged.

---

## 5. Information architecture

### 5.1 Primary navigation

| Item | Children | Notes |
|---|---|---|
| Home | | |
| About | The registry · Mandate and law · How it works · Governance | |
| Statistics | Coverage · Poverty bands · Demographics · Downloads | Aggregates only |
| Services | Check my status · Lodge a grievance · Request data | The three public services |
| Publications | Reports · Policy documents · Data catalogue | GOU-mandated |
| News | | Hidden until a content owner is named. LP-O-05. |

**Header CTA:** `Request data`. Filled, `--public-accent`. One CTA only.

**Utility row** (in the government banner): search, language switch, contact, text-size and high-visibility toggle.

### 5.2 Footer

Four columns plus a legal bar.

1. NSR identity: logo, one-paragraph description, ownership line.
2. Quick links: About, Statistics, Publications, FAQ, Sitemap, Feedback.
3. Services: Check status, Lodge a grievance, Request data, Developer portal.
4. Contact: toll-free number, `nsr@mglsd.go.ug`, postal address, social links.

Legal bar: copyright, privacy notice, terms, disclaimer, accessibility statement, "Page created {{date}} · Last updated {{date}}".

---

## 6. Page structure

Twelve sections. Alternating `--neutral-0` and `--public-surface-alt` backgrounds, except S1 and S9 which run dark.

### S1 · Hero

| Field | Value |
|---|---|
| Background | Linear gradient `--public-hero-bg` to `--public-hero-bg-deep`, 160 degrees. Subtle 4% dot pattern. |
| Layout | Two columns at ≥1024px, 7/5 split. Stacked below. |
| Left | Eyebrow chip, H1, standfirst, two buttons |
| Right | Four counter cards in a 2x2 grid |
| Height | `min-height: 560px`, never a fixed viewport height |

Copy slots:

- Eyebrow: `{{Uganda's National Social Registry}}`
- H1: `{{One register. Every household. Fair targeting.}}` Max 8 words. One word may take `--public-accent` and italic, as GNHR does with "trusted".
- Standfirst: `{{40 to 55 words on what the registry is and who it serves.}}`
- Primary button: `Request data` → `/services/data-request`
- Secondary button: `Check my status` → `/services/status`, ghost style, 1px `--neutral-0` border

Counter cards (2x2):

| Card | Placeholder | Source | Refresh |
|---|---|---|---|
| Households registered | 0,000,000 | RPT public aggregate | Nightly |
| People covered | 0,000,000 | RPT public aggregate | Nightly |
| Sub-regions | 9 | REF-DATA, static | On geography version change |
| Districts reached | 000 of 000 | RPT public aggregate | Nightly |

Rules: server-render the numbers into the HTML. No client fetch on first paint. Count-up animation runs once per session and is skipped under `prefers-reduced-motion`. Every counter carries an `as at {{date}}` caption. A stale or failed aggregate renders the last good value with its date, never a spinner and never zero.

### S2 · Trust bar

Thin strip directly under the hero. Four short claims with icons, no cards.

`{{Backed by law}}` · `{{Verified against NIRA}}` · `{{Your data is protected}}` · `{{Independently audited}}`

Each links to the relevant About page. Height 72px. Background `--neutral-0`.

### S3 · About the registry

Centred intro then a four-card grid.

- Eyebrow: `ABOUT THE NSR`
- H2: `{{A single register for social protection}}`
- Intro: `{{45 words. Name the mandate, the ministry, and the PMT method.}}`

Cards, icon plus title plus 25 words:

| Card | Angle |
|---|---|
| One national register | Scale and single source of truth |
| Verified identity | NIRA validation, deduplication |
| Objective targeting | PMT, dual approval, no discretion |
| Protected by law | DPPA 2019, consent, audit chain |

Card spec: `--radius-card`, `--shadow-card`, `--space-6` padding, icon in a 40px tinted square using the matching module accent from `tokens.css`.

### S4 · Statistics at a glance

The section GNHR does best. Four blocks.

**4a. KPI row.** Six cards, `KPI card` component from `components.md` §5.6, no sparkline. Households registered, people covered, average household size, districts, sub-counties, parishes.

**4b. Coverage by band.** Horizontal bar chart, five bands (below 25%, 25 to 50%, 50 to 75%, 75 to 100%, above 100% of projected households), value labels inside the bar. Colour by band using `--accent-danger`, `--accent-quality`, `--accent-eligibility`, `--accent-data`, `--accent-update`. Never colour alone: each band carries its label and count.

**4c. Sub-region choropleth.** Static SVG map of Uganda's nine sub-regions on the homepage. No tile provider, no API key, no external dependency. Hover shows a tooltip, click goes to `/statistics?region=`. A data table with the same numbers sits directly below, collapsed behind a `Show as table` toggle. The table is the accessible equivalent, not an afterthought.

**4d. Demographics strip.** Sex split, age bands, disability prevalence, female-headed households. Percentages plus absolute values.

Section CTA: `See full statistics` → `/statistics`.

**Every chart in this section carries:** a title, a one-line method note, an `as at` date, and a `Download CSV` link.

### S5 · How the registry works

Six numbered cards, GNHR's strongest structural idea, mapped onto our actual modules.

| # | Step | Module |
|---|---|---|
| 1 | Community entry and sensitisation | Field operations |
| 2 | Household data collection | INT (CAPI, web, USSD) |
| 3 | Quality checks and identity verification | DAT-DQA, DAT-DDUP, IDV |
| 4 | Welfare scoring | PMT |
| 5 | The register | DAT |
| 6 | Programme targeting and referral | REF |

Each card: step number in a filled circle, icon, title, 25 words. Card 6 uses `--public-accent` on the number circle to close the sequence.

Below the grid: one line pointing to the detailed process page.

### S6 · Public services

The section GNHR does not have. Three equal cards on a `--public-surface-alt` band. This is the page's second most important block after the hero.

| Card | Heading | Body | CTA | Module | Release |
|---|---|---|---|---|---|
| A | Check my registration status | `{{Confirm if your household is on the register and what stage it has reached.}}` | `Check status` | DAT read-only view | R1 |
| B | Lodge a grievance | `{{Report a wrong record, an exclusion, or a complaint. Track it with a reference code.}}` | `Lodge or track` | GRM | R1 |
| C | Request registry data | `{{Government agencies, programmes and researchers can request data under a signed agreement.}}` | `Start a request` | API-DRS | R1 |

Detail for each in §7.

### S7 · Data access explainer

Dark band, mirrors GNHR's "Access GNHR Data" section. Two columns.

Left: H2 `{{Access registry data}}`, 35-word standfirst, then three numbered steps.

| Step | Placeholder text |
|---|---|
| 1 · Submit a request | `{{Complete the online form. Name your organisation, the data you need, and your purpose.}}` |
| 2 · Review and agreement | `{{The NSR Unit and the Data Protection Officer review the request against your Data Sharing Agreement.}}` |
| 3 · Secure delivery | `{{Approved extracts arrive encrypted and watermarked, or through a paginated API.}}` |

Right: a raised card. Icon, `Quick data request`, one line, filled `--public-accent` button.

Add one line GNHR omits and every requester asks about: `{{Typical turnaround: {{n}} working days from a complete request.}}` The number needs an owner. LP-O-03.

### S8 · Publications and downloads

Three-column card grid. Reports, policy documents, the data catalogue. Each card shows title, type badge, file size, date. GOU standards require this section.

### S9 · News and events

Three cards, image, category chip, title, 20-word teaser, date. `View all news` link right-aligned on the heading row.

**Hidden in v1** unless MGLSD names a content owner. An empty or stale news section damages a government site more than a missing one. LP-O-05.

### S10 · Partners

Grey-scale logo strip, saturating on hover. MGLSD, NITA-U, NIRA, UBOS, OPM, World Bank, and programme partners (SAGE, NUSAF, PDM). Single row on desktop, two-row wrap on mobile, no carousel.

### S11 · Helpline band

Full-width, `--public-band-helpline`. Phone icon, `{{NSR Helpline}}`, `{{Toll free}}`, and the number at `--fs-section` weight 700. One line, high legibility, impossible to miss. Add operating hours, which GNHR omits and which drives repeat calls.

### S12 · Footer

Per §5.2.

---

## 7. The four public services in detail

### 7.1 Check my registration status

The privacy-sensitive one. Design it defensively.

**Do not** accept a bare NIN or a name as the lookup key on a public page. Either one turns the page into an enumeration oracle: an attacker walks a NIN range and learns who is on the poverty register. That is a reportable breach under DPPA 2019.

**Proposed flow:**

1. Household enters the **registration reference code** from their receipt slip (`/design/v0.1/screens/02_receipt_slip.html`) plus the **phone number** recorded at capture.
2. System sends a 6-digit OTP to that phone. Rate limited: 3 attempts per code per hour, 5 per IP per hour, with a visible cool-down.
3. On success the page returns **status only**:

| Returned | Not returned |
|---|---|
| Lifecycle state chip: Provisional, Pending, Registered, Rejected, Voided | Names, NIN, GPS, ages, any member detail |
| Date of last change | PMT score |
| Sub-county of registration | PMT band or poverty classification |
| What happens next, in one sentence | Programme enrolment or payment status |
| A link to lodge a grievance | Anything about any other household |

4. Session expires in 10 minutes. No result is cached, indexed, or bookmarkable. `noindex` on the result URL.

**PMT band stays hidden.** Publishing a household's poverty classification invites both stigma and gaming. If MGLSD wants it shown, that is a policy decision with a DPIA attached, not a UI decision. LP-O-04.

**Reuse the console status vocabulary** from `tokens.css`: `.chip--provisional`, `.chip--pending`, `.chip--registered`, `.chip--rejected`, `.chip--voided`. One vocabulary across every surface.

**Audit.** Every lookup attempt writes a SEC `AuditEvent`, successful or not, per the CLAUDE.md rule that any read of personal data is audited.

**Accessibility.** OTP field is a single `input` with `autocomplete="one-time-code"` and `inputmode="numeric"`, not six boxes. Six boxes break screen readers and paste.

### 7.2 Lodge a grievance

Public intake into GRM. Two modes on one page: **Lodge new** and **Track existing**.

**Lodge new,** four steps with a progress indicator:

1. **Category.** Controlled list from `GrievanceCategory` in REF-DATA. Plain-language labels, not internal codes.
2. **Details.** Free text, 1000 characters, plus optional file attachment (photo of a document, 5MB, JPG/PNG/PDF only, server-side type check).
3. **Who and where.** Name, phone, sub-county from the UBOS hierarchy picker. Registration reference code optional. Anonymous submission allowed, with a clear warning that anonymous cases cannot be updated by phone.
4. **Consent and submit.** Explicit consent checkbox with the privacy notice inline, not behind a link. Unticked by default.

On submit: show a **case reference code** on screen, send it by SMS, and state the SLA and the tier the case entered (L1 Parish Chief). Print-friendly confirmation.

**Track existing:** reference code plus phone, then OTP. Returns case status, tier, date opened, last update, and a resolution narrative when closed. No reviewer names and no internal notes.

**Abuse controls.** CAPTCHA is the obvious answer and the wrong one: it blocks low-literacy users, the exact people the registry serves. Use rate limiting by phone and IP, a honeypot field, and a server-side minimum completion time instead. Never place a CAPTCHA between a citizen and a complaint mechanism.

### 7.3 Request registry data

Public-facing front end for API-DRS.

Unauthenticated visitors see: what data exists (the catalogue), who may request it, what a DSA requires, the turnaround, and the request form. They never see the Query Builder. The Query Builder, Field Selector, preview and delivery screens are behind Keycloak and already specified in `/design/v0.1/screens/07_drs_*.html`.

Public form fields: organisation, type (MDA, programme, research, NGO, donor, internal M&E), contact person, official email (validate the domain against an allow-list where possible), purpose, data described in plain language, requested period, geography, DSA status (existing reference or new).

On submit: reference code on screen and by email, plus the next step and the SLA. Route into the API-DRS approval queue with the DPO gate.

**Publish the data catalogue as a public page.** Entity, field, sensitivity chip (`.chip--public`, `.chip--internal`, `.chip--personal`, `.chip--sensitive`), and if a DSA is needed. Requesters who can see the field list ask for the right things, which cuts the review load. GNHR does not do this. It is the single highest-value addition on this page.

### 7.4 Open statistics

Homepage carries the summary. `/statistics` carries the depth: filters by sub-region, district, and time; tabbed views for coverage, poverty bands, demographics, and data quality; CSV and XLSX download on every view; a methodology note on every chart.

Backed by RPT public aggregates, served from a read replica or a nightly materialised view. Never a live query against the registry. Cache at the edge for 24 hours.

---

## 8. Publishing rules for public statistics

### 8.1 Aggregates only

No row-level data on any public URL, in any format, including CSV downloads.

### 8.2 Geographic floor

Publish freely at national, sub-region, and district level. Below district, apply §8.3 before anything is published.

### 8.3 Disclosure floor

Proposed and awaiting DPO sign-off (LP-O-06):

- Suppress any cell built on fewer than **10 households**. Show `..` and a footnote, not a zero.
- Suppress complementary cells where a suppressed value could be recovered by subtraction.
- No cross-tabulation deeper than two dimensions on the public site.
- No disability, health, or other special-category breakdown below district level.
- Round percentages to one decimal. Round counts below 100 to the nearest 5.

### 8.4 Provenance

Every published figure carries an `as at` date, the source module, and the method note. Every downloadable file carries the same in a header row. A number without a date is a liability.

---

## 9. Responsive behaviour

| Breakpoint | Layout |
|---|---|
| ≥1280px | Full 12-column grid, `--public-content-max` 1200px, hero 7/5 |
| 1024 to 1279px | 12 columns, gutters tighten to `--space-6` |
| 768 to 1023px | Hero stacks, counters go 4-across, card grids go 2-across |
| 480 to 767px | Single column, counters 2x2, nav collapses to a drawer |
| <480px | Single column, counters stack, section padding drops to `--space-7` |

Touch targets 44x44px minimum. The nav drawer is a real `<dialog>` or a focus-trapped panel, with ESC to close.

**Bandwidth is a design constraint, not an afterthought.** SAD §3.2 records unreliable connectivity at parish and sub-county level. Budget in §12.

---

## 10. Motion

Minimal. Counter count-up once per session, card hover lift of 2px, chart draw-in of 400ms. Nothing autoplays, nothing loops, nothing scrolls by itself. GOU standards prohibit scrolling and blinking text, so the incumbent site's auto-advancing carousel does not carry over.

All of it wrapped in the `prefers-reduced-motion` block already present in `tokens.css`.

---

## 11. Accessibility gates

WCAG 2.1 AA. These are pass/fail at review.

1. Colour ratio 4.5:1 for body text (WCAG 1.4.3), 3:1 for large text and UI components. Verified for every token pair in §4.2.
2. Keyboard reachable in a logical order, with a visible focus ring using `--focus-ring`. A `Skip to content` link is the first focusable element.
3. Every chart has a text alternative: a data table, either visible or behind a `Show as table` toggle.
4. Never colour alone. Every band, chip and map class carries a label.
5. Landmarks: one `<h1>`, no skipped heading levels, `<nav>`, `<main>`, `<footer>` present.
6. Forms: visible labels, not placeholders. Errors named in text, listed at the top of the form, and linked to the offending field.
7. The map has a keyboard-operable equivalent. The table is it.
8. Zoom to 200% with no horizontal scroll and no clipped content.
9. Tested with NVDA and with VoiceOver on iOS.
10. Accessibility statement published and linked in the footer.

---

## 12. Performance budget

| Metric | Budget |
|---|---|
| HTML, gzipped | 40KB |
| CSS, gzipped | 25KB |
| JS, gzipped, initial | 60KB |
| Fonts | 2 weights, WOFF2, subset Latin, `font-display: swap` |
| Largest Contentful Paint, 3G | under 3.0s |
| Total first-load transfer | under 500KB |
| Lighthouse performance | 90 or above on mobile |

Rules: server-render the hero and counters. Lazy-load below-fold images with explicit `width` and `height`. Charts render as inline SVG, no charting library on the homepage. Self-host fonts, no third-party CDN. No tile-server map on the homepage.

---

## 13. Internationalisation

English at launch, per SAD §10.4. The build must be ready for Luganda and Runyankole in Release 2, Acholi and Lusoga in Release 3.

- Every string goes through the translation framework from day one, including English.
- No text baked into images.
- Layouts absorb 35% string expansion without breaking.
- The language switch sits in the government banner utility row and persists by cookie.
- Numerals and dates render in the East Africa Time locale.

---

## 14. Open items

| ID | Item | Owner | Needed by |
|---|---|---|---|
| LP-O-01 | Does this site replace `nsr.mglsd.go.ug` v2.0, or run beside it? | NSR Unit + MGLSD ICT | Before build |
| LP-O-02 | Fate of the incumbent APPLICANTS / PAYMENTS / EXITS sections | NSR Unit | Before build |
| LP-O-03 | Published turnaround time for data requests | NSR Unit + DPO | Before content freeze |
| LP-O-04 | Is a household's PMT band shown in the status check? Recommendation: no | DPO + Policy | Before R1 |
| LP-O-05 | Content owner for News and Publications. No owner, no section | NSR Unit Communications | Before launch |
| LP-O-06 | Sign off the disclosure floor in §8.3 | DPO | Before statistics go live |
| LP-O-07 | Toll-free number and operating hours for the helpline band | NSR Unit | Before launch |
| LP-O-08 | Coat of Arms usage approval and asset in SVG | MGLSD ICT | Before build |
| LP-O-09 | Anonymous grievances: allowed or not? | GRM owner + DPO | Before R1 |
| LP-O-10 | Hosting: NITA-U GDC alongside the MIS, or a separate public zone with no route to the registry network? Recommendation: separate zone | NITA-U + Security | Before build |

---

## 15. Acceptance gates

Run at 1366 wide, then at 375 wide, then with the keyboard only, then with a screen reader.

| # | Gate |
|---|---|
| 1 | Every colour, font size and spacing value resolves to a variable in `tokens.css` or the §4.2 additions. No hardcoded hex anywhere. |
| 2 | No personal data appears on any public URL, in any state, including error states. |
| 3 | Every published statistic carries an `as at` date and a method note. |
| 4 | Every chart has a table equivalent reachable by keyboard. |
| 5 | Hero counters render server-side and survive an aggregate service outage without showing zero. |
| 6 | Status check refuses a bare NIN and enforces OTP plus rate limiting. |
| 7 | The grievance form works with no JavaScript beyond validation, and shows a reference code on submit. |
| 8 | Coat of Arms, ministry name, ownership line, created and updated dates, privacy, terms and disclaimer are all present. |
| 9 | Lighthouse mobile: performance 90 or above, accessibility 100. |
| 10 | Page loads and remains usable on a throttled 3G connection. |
| 11 | Every user-facing string passes through the translation framework. |
| 12 | Nothing autoplays, blinks or scrolls by itself. |

---

## 16. Backlog stories to raise

Not yet in `/docs/03_backlog.xlsx`. Suggested epic: **17. Public Website**.

| Proposed ID | Story | Module | MoSCoW |
|---|---|---|---|
| US-P01 | Public landing page with server-rendered hero counters | RPT | Must |
| US-P02 | Public statistics page with sub-region filters and CSV download | RPT | Must |
| US-P03 | Public aggregate API with the disclosure floor applied | RPT + API | Must |
| US-P04 | Household status check with reference code and OTP | DAT + SEC | Must |
| US-P05 | Public grievance intake and tracking | GRM | Must |
| US-P06 | Public data request form routed into the API-DRS queue | API-DRS | Must |
| US-P07 | Public data catalogue with sensitivity badges | API-DRS | Should |
| US-P08 | Publications and downloads library | RPT | Should |
| US-P09 | Language switch with Luganda and Runyankole | Cross-cutting | Should (R2) |
| US-P10 | News and events, admin-managed | Cross-cutting | Could |

---

## 17. Next steps

1. Close LP-O-01 and LP-O-02. Everything else depends on knowing which site this is.
2. Get MGLSD to approve the section list in §6 before anyone writes copy or code.
3. Build a clickable HTML mockup of S1 to S6 against the §4.2 tokens.
4. Take the mockup to the DPO with §7.1 and §8.3 as the agenda.
5. Raise the §16 stories into the backlog.

---

**End of spec. Version 0.1, 29 August 2026.**
