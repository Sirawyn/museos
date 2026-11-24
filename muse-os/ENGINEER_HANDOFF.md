# Muse Hospitality: engineer handoff

*Last updated 2026-11-12. Covers the Instagram DM bot and the Muse OS web app.*

This document has no secret values. Every token, key and password is named by its environment variable only. Ask the owner (Devin) for access to Render, GitHub, the Meta developer app and the Muse OS server.

---

## 0. Changes since the previous handoff (2026-11-11, 07:06 UTC)

**Latest, 2026-11-17 night: leads make their own booking.** Saving a lead in the web app (`app/main.py`, `sync_lead_booking`) with status Confirmed plus night, venue and IG handle creates its booking (stop 1, lead_id set, venue night ensured) if it has none. Later saves copy night/venue/handle/host/party/girls/guys to that booking while it is a single, still-Confirmed booking (checked-in or multi-stop bookings are left alone). Status Lost cancels its Confirmed bookings. Runs on every save, so leads confirmed earlier get a booking the next time they're saved. The bot API path is unchanged. Tests: `tests/test_lead_booking_sync.py` (4).

**2026-11-17 evening: bulk delete for admins.** Leads, Guests and Bookings lists show a checkbox per row, "Select all on this page" and "Delete N selected" (with a confirm) for admins only. New route `POST /{slug}/delete-selected` in `app/main.py` (admin + CSRF, only those three tabs, each row audited as "delete (bulk)"); `list.html`, `app.js`, `style.css`; tests `tests/test_bulk_delete.py` (2).

**2026-11-17: Social planner in Muse OS** (for the two social media managers). New `app/social.py` (hub, calendar, approval rule, actions), `app/social_seed.py` (one-off seed of the current campaigns, the 14 Thalia series posts, Monday recaps, Going Out With Muse posts and 18 backlog ideas, guarded by settings key `seeded_social_v1`), five new tables created by `db.init()` (`plan`, `campaigns`, `ideas`, `shoots`, `growth`, no migration needed), new tabs in `schema.py`, `social` role can view and edit them (`auth.py`), templates `social.html` and `calendar.html`, `form.html` approval/idea/campaign panels, nav changes, CSS. Social logins now land on `/social`. New settings keys: `follower_goal`, `follower_goal_date`, `weekly_reels`, `weekly_carousels`, `reel_bonus_views`, `reel_bonus_max`, `creator_tracker_url`. Tests: `tests/test_social.py` (8). Deploy as usual: copy the code and `docker compose up -d --build`; data in the volume is kept. Note: `tests/test_api.py::test_booking_host_is_the_host_on_duty` fails on any date after 2026-11-14 because it hard-codes that night as "upcoming"; it failed the same way before this change.

**Latest, 2026-11-12: NOFLEX is cover only (no guys' tickets).** The owner types the cover price for each NOFLEX night every Sunday and the bot quotes it.
- **Muse OS** (`app/db.py`, `app/admin.py`, `app/templates/setup.html`, `tests/test_setup.py`): NOFLEX's *Guys' entry* is now "Cover at the door" (fresh installs via `COVER_VENUES` in `db.py`; existing databases via a one-off migration in `db.init()` that only touches NOFLEX when its Guys' entry is blank or Ticket, guarded by the settings key `migrated_noflex_cover`, so a later change on the Venues page sticks). On Weekly setup, any night whose guys' entry is Cover at the door shows a labelled **"Cover this night"** box (e.g. $20) and no per-night ticket link box; section 2 shows "Cover at the door, no ticket link" for that venue instead of a link input (the stored link is carried through as a hidden field, not wiped). Nothing changed in the API: the price goes out as `venues[].upcoming[].cover` and the policy as `guys_policy: "cover"`. 57 tests pass.
- **DM bot** (`config.yaml`, `muse_bot/engine.py`, `tests/test_engine.py`): `noflex.guys_policy` is now `cover`. Guests asking about guys at NOFLEX, and NOFLEX confirmations with guys, get "The guys just pay a $20 cover at the door, they don't need a ticket." (or "The guys just pay cover at the door, they don't need a ticket." when no price is set yet), never the "I'll send you the link soon" line, and the team is no longer alerted to send a NOFLEX ticket link. The Monday noon check (`weekly_ticket_check`) now also sends "💵 No cover price yet this week for NOFLEX Thursday, ..." when a cover-only night that week has no price. 188 tests pass (`tests` + `integration`).

**Muse OS** (`app/calc.py`, scout home page, `README.md`, tests):
1. **Scouts are paid only for first-time girls.** A scout earns only on a guest's first booking that got in (matched by IG handle, earliest night counts, later ones don't), and still only at per-girl venues. New `World.first_visits()` and `is_first_time()` in `app/calc.py`. The scout's home page labels uncredited repeats "returning guest". 55 tests pass.

(The Engineer role, free guys' entry, per-night guys' entry and per-person hidden columns/days were already in the previous zip.)

**DM bot** (`config.yaml`, `muse_bot/engine.py`, `README.md`, `tests/test_engine.py`):
1. **Promoter hold-off cut from 12 hours to 10 minutes.** `human_takeover_hours` replaced by `human_takeover_minutes: 10` (the old key still works as a fallback). The timer restarts with every promoter message.
2. **Double-text resumes the bot.** If the girl sends 2 messages with no promoter reply in between and the bot has a real answer (new `_can_answer()`), the hold-off ends early. Counter stored per chat in the settings table as `texts_since_human:<ig_user_id>`.
3. **New wording throughout.** Every guest-facing message rewritten in a young, casual voice (e.g. "What night are you thinking?", "Is everyone 21+? They only take physical IDs at the door", "Love a big group!"). Only `config.yaml` changed for this.
4. **Hosts by first name only** in guest messages.
5. **Missing ticket link wording:** new `guys_ticket_nolink` message ("The guys just need a ticket, I'll send you the link soon!") instead of inserting "we'll send you the link" into the link slot. Team alert unchanged.
6. **Bug fix, over-21 "yes":** a plain "yes" now counts as over 21 only when the bot just asked the age question, so "yes 2 guys" answers the guys question instead.
7. **Bug fix, other-venue false positives:** phrases like "this weekend", "a table", "the list", "drinks", "bottles", "a party", "promos" are no longer mistaken for a club Muse doesn't work with (which would have silently handed the chat off).
8. Tests: 187 pass (`tests` + `integration`), up from 181.

---

## 1. The two systems at a glance

| | **Muse DM bot** | **Muse OS** |
|---|---|---|
| What it does | Answers Instagram DMs to the @musehospitalitynyc account, qualifies guests for the guestlist, confirms them, sends next-day follow-ups, alerts the team | Private web app for running nights: leads, guests, bookings, door check-in, venues, weekly lineup, team pay, revenue |
| Stack | Python 3.12, FastAPI, uvicorn, httpx, PyYAML, SQLite | Python 3.12, FastAPI, Jinja2 server-rendered pages, SQLite |
| Hosting | Render (Docker, Starter plan, 1 GB disk at `/data`), deployed from the private GitHub repo `muse-dm-bot` via `render.yaml` Blueprint | Self-hosted on a Linux VPS with `docker compose`: app + backup container, behind the server's Traefik (auto HTTPS) |
| Source of record | Its own SQLite (`/data/muse_leads.db`) for conversation state | **System of record** for leads, guests, bookings, venues, lineup |
| Code location | Project Library: `muse-dm-bot/` (also copied to the owner's Mac at `~/Downloads/muse-dm-bot`) | Project Library: `muse-os/` (also `muse-os.zip`) |
| Tests | `python -m pytest -q tests` (187 pass as of this handoff, incl. `integration/`: `python -m pytest -q tests integration`) | `python -m pytest -q tests` (55 pass) |
| Status | **Live on Render.** Instagram connection works end to end for tester accounts. | **Code complete. Not confirmed deployed yet.** The bot has no `MUSE_OS_URL` set until it is. |

---

## 2. Architecture and how they integrate

```
  Guest (Instagram)
        │ DM
        ▼
  Meta Graph API ──webhook POST /webhook──►  DM bot (Render)  ──Slack/Discord webhook──► team channel
        ▲                                     │   │
        └──── POST /{IG_ACCOUNT_ID}/messages ─┘   │  every 5 min (background loop)
                                                  │   GET  /api/v1/venues, /scouts, /checkins
                                                  │   PUT  /api/v1/leads/{id}, /guests/{handle}, /bookings/{id}
                                                  ▼
                                        Muse OS (VPS, Traefik HTTPS)
                                                  ▲
                                 Admins / hosts / promoters / scouts in the browser (phone at the door)
```

**Direction of data.** Muse OS never calls the bot. The bot pulls from Muse OS and pushes to it.

- **Pushes (near real time):** when a conversation changes, the lead is marked dirty and the next sync pushes it. Lead ids are `DM-00001`, booking ids `BK-DM-00001`. Lead status mapping (bot → Muse OS): qualifying → Qualifying (New until the first reply), needs_human → Qualified, confirmed → Confirmed, arrived → Arrived, no_show → No-show, dropped/cancelled → Lost. New guests are created; existing guests are left alone so tags and notes stay. A confirmed group becomes a booking assigned to that night's host on duty.
- **Pulls (every 300 s, `server.py` background loop):** per venue: usual nights, the dated lineup for the next 14 nights (host, dress code, guys' cover, ticket link, list close time per night), confirmation message template (`[HOST]` and `[DRESS_CODE]` placeholders), venue ticket link, guys' policy, list close time; active scouts; door check-ins and no-shows since the last cursor.
- **Failure behaviour:** if Muse OS is down, the bot logs it and keeps using the last known venue data and its `config.yaml` fallback. Replies and follow-ups never depend on Muse OS being up. Failed lead pushes are retried on the next loop.
- **Guard rails in the API:** the bot's key cannot read money, the Ledger or logins. A host's Arrived/No-show is never downgraded by the bot, and once a host has checked a booking in, the bot can't overwrite its status or count.

**The same 5-minute loop also:** renews the token in Instagram-login mode only and, under Unified login, checks the token's expiry once a day (section 5), sends the Monday noon missing-ticket-link alert, sends the 9pm nightly list digest, runs next-day follow-ups (thank-you / "we missed you" at 1pm) and the no-show sweep (night ends at 5am).

### Muse OS API (used by the bot)

Auth: `Authorization: Bearer <MUSE_OS_API_KEY>`. JSON bodies; unknown fields are rejected.

| Endpoint | Purpose |
|---|---|
| `PUT /api/v1/leads/{lead_id}` | Create/update a lead (also adds the guest if new) |
| `PUT /api/v1/guests/{ig_handle}` | Add a guest if new |
| `PUT /api/v1/bookings/{booking_id}` | Create/update a booking (night, venue, ig_handle required) |
| `GET /api/v1/venues` | Venues, nights, door info, guys' policy, list close time, `upcoming[]` lineup (no pay terms) |
| `GET /api/v1/scouts` | Active scouts (name, handle) |
| `GET /api/v1/checkins?since=…` | Door check-ins / no-shows / undos since the last call |

The bot's client is `muse-dm-bot/muse_bot/museos.py`, a copy of `muse-os/integrations/museos.py` with two local changes (noted in its header). Keep them in sync when the API changes.

---

## 3. Connecting the bot to Muse OS (step by step)

Do this once Muse OS is running at a public HTTPS address (section 6). Render's outbound IPs aren't fixed, so don't IP-restrict the Muse OS API.

1. **Confirm Muse OS is reachable.** Open `https://<muse-os-domain>/healthz` from any browser. It should answer OK.
2. **Create the bot's API key in Muse OS.** Log in as an admin and go to **Admin > DM bot API** (`/admin/keys`), then **Create key**. The key is shown once, so copy it straight into step 3. (Alternative on the server: `docker compose exec app python -m app.cli create-api-key "DM bot"`.) Keys are stored hashed and can be revoked on the same page.
3. **Set two variables on the bot in Render.** Render > `muse-dm-bot` service > **Environment**:
   - `MUSE_OS_URL` = `https://<muse-os-domain>` (must start with `http`, no trailing path)
   - `MUSE_OS_API_KEY` = the key from step 2

   Save. Render redeploys in 2 to 4 minutes (watch **Events** for "Deploy live").
4. **Check the key works from outside** (optional, from your laptop):
   ```
   curl -s -H "Authorization: Bearer $MUSE_OS_API_KEY" https://<muse-os-domain>/api/v1/venues | head
   ```
   You should get `{"venues": [...]}`. A 401 means the key is wrong or revoked.
5. **Fill the data the bot reads.** In Muse OS: Venues page (nights, confirmation message, guys' entry, guestlist close time, dress code, arrive by), Team page (scouts with role Scout), and **Admin > Weekly setup** (`/setup`) for this week's lineup with a host per venue night.
6. **Watch the first sync.** In Render **Logs**, within 5 minutes there should be no `Muse OS read failed` lines. If there are, the URL or key is wrong, or Muse OS isn't reachable.
7. **End-to-end test.** From a tester Instagram account, DM the Muse account (e.g. "can 3 of us come friday? all girls, all 21"). Within seconds a lead `DM-000xx` should appear on the Muse OS Leads page, and after the confirmation a booking on that host's **Tonight** list. Check the guest in at the door in Muse OS; within 5 minutes the bot picks it up, and the next day at 1pm the guest gets the thank-you instead of "we missed you".
8. **Automated check (optional):** `muse-dm-bot/integration/test_museos_e2e.py` runs the bot against a real Muse OS instance.

Without these two variables the bot still replies, using `config.yaml` for venues and schedule, but leads stay only in the bot's own database and it can't see the weekly form or door check-ins.

---

## 4. Environment variables (names only)

### DM bot (Render)

| Variable | Required | What it is |
|---|---|---|
| `META_LOGIN` | yes | `unified` (current). Legacy values `instagram` and `facebook` still supported. Set in `render.yaml`. |
| `IG_ACCESS_TOKEN` | yes | Token generated for the Muse account under *API setup with Unified login > Generate access tokens* |
| `IG_ACCOUNT_ID` | yes | Instagram professional account ID shown next to the account on that page (starts with 178…) |
| `META_APP_SECRET` | yes | Used to verify `X-Hub-Signature-256` on webhook POSTs. With Unified login Meta may sign with the **Instagram app secret** on the Unified login page rather than *App settings > Basic*; if POSTs get 403, swap it. |
| `VERIFY_TOKEN` | yes | Shared secret entered in the Meta webhook config; checked on `GET /webhook` |
| `ADMIN_TOKEN` | yes | Protects the team links (`/report`, `/leads.csv`, `/check-meta`, the POST actions). Use letters and digits only (symbols get mangled in URLs). |
| `MUSE_OS_URL` | for sync | Muse OS base URL |
| `MUSE_OS_API_KEY` | for sync | Key from Muse OS Admin > DM bot API |
| `NOTIFY_WEBHOOK_URL` | recommended | Slack or Discord incoming webhook for team alerts (sends both `text` and `content`). Without it alerts go only to logs. |
| `FB_PAGE_ID` | legacy | Only for `META_LOGIN=facebook` |
| `GRAPH_VERSION` | optional | Default `v23.0` |
| `MUSE_DB` | set in Dockerfile | `/data/muse_leads.db` (on the Render disk) |
| `MUSE_CONFIG` | optional | Default `config.yaml` |
| `PORT` | Render sets it | uvicorn port |

### Muse OS (VPS)

| Variable | Where | What it is |
|---|---|---|
| `DOMAIN` | `.env` (copy of `.env.example`) | Hostname Traefik serves and gets a certificate for, e.g. `os.musehospitality.com` |
| `MUSE_DB` | Dockerfile | `/data/muse.db` inside the `muse-data` volume |
| `MUSE_INSECURE_COOKIES` | local dev only | `1` disables Secure cookies for plain-http localhost. Never set in production. |

---

## 5. Meta / Instagram setup (current state)

- **Account:** @musehospitalitynyc, a Professional account. *Settings > Messages and story replies > Message controls > Connected tools > Allow access to messages* must be on.
- **Meta app** (developers.facebook.com): use case *Manage messaging & content on Instagram*, **API setup with Unified login**. No Facebook Page is needed. The owner chose Unified login on 2026-11-10, over Facebook login.
- **Graph host:** the bot tries `graph.facebook.com/v23.0` and `graph.instagram.com/v23.0` and remembers whichever works (stored in the bot's settings table as `graph_base`). `GET /check-meta?token=<ADMIN_TOKEN>` shows both results. On 2026-11-10 **graph.facebook.com accepted the token** and graph.instagram.com rejected it with "Cannot parse access token" (expected for this token type).
- **Sending:** `POST {graph_base}/{IG_ACCOUNT_ID}/messages` with `recipient.id` and `message` (text plus up to 13 quick replies, 20 characters per title). Profile lookup is `GET {graph_base}/{ig_user_id}?fields=username,name`.
- **Webhook:** callback `https://<render-address>/webhook`, verify token = `VERIFY_TOKEN`, field **`messages`** subscribed (this was off at first and was why the first test got no reply). Under *Generate access tokens*, **Webhook subscription** is on for the Muse row only, not for any personal tester account.
- **Roles:** testers are added under *App roles > Roles > Instagram Tester*. Invites are accepted at instagram.com > Settings > Apps and websites > Tester invites (the website, not the phone app).
- **Token expiry and renewal:** Unified-login tokens can't be refreshed automatically. Once a day the bot asks Meta (`debug_token`) when the token expires, and starting 10 days before expiry it sends a warning every day to `NOTIFY_WEBHOOK_URL` (or to the Render logs if that isn't set). `/check-meta` shows a `token_expiry` field. **To renew:** Meta app > Instagram > API setup, generate a new token for the Muse account, and paste it into `IG_ACCESS_TOKEN` on Render. The bot switches to the new token on the next deploy.
- **Privacy policy / data deletion URLs** for the Meta app are served by the bot: `/privacy` and `/data-deletion` (`muse_bot/static/privacy.html`). Review the wording; it's written in Muse's name.
- **Publishing:** the owner published the app on 2026-11-10. Whether non-testers get replies without App Review is **not yet confirmed** (see open items).
- **Platform rules built into the bot:** replies only (never DMs first), automated messages only within 24 hours of the guest's last message (otherwise logs `skipped_outside_24h`), human always reachable, official API only. Comments are not read; story replies arrive as DMs and are handled.

---

## 6. Deployment

### DM bot on Render

- Repo: private GitHub `muse-dm-bot`, with `render.yaml` at the repo root. Render > New > Blueprint created a Docker web service (`plan: starter`, health check `/health`, disk `data` at `/data`, 1 GB).
- **Deploys:** every push to the repo redeploys automatically. Up to now the owner has updated the repo by **drag-and-drop upload in the GitHub web UI** from `~/Downloads/muse-dm-bot`. The newest code is in the project Library `muse-dm-bot/`. **First task: diff the GitHub repo against the Library copy** and push anything missing. Several fixes from late 2026-11-10 (one question per message, fewer emojis, venues we don't work with, big groups, list close times, per-night ticket links, cover-only venues) may not have been uploaded yet. Move to normal git pushes from here.
- Use the paid Starter plan. The free plan sleeps and adds about a minute of wake-up latency.
- Endpoints: `GET /health`, `GET|POST /webhook`, `GET /privacy`, `GET /data-deletion`, and with `ADMIN_TOKEN`: `GET /check-meta?token=`, `GET /report?token=`, `GET /leads.csv?token=`, `POST /leads/{id}/checkin?count=N`, `POST /leads/{id}/confirm`, `POST /guests/{ig_user_id}/resume`.
- Run locally: `pip install -r requirements.txt`, then `python simulate.py` (terminal chat as a guest; `/time 2026-11-12 23:20`, `/human hi`, `/checkin`, `/jobs`, `/report`), or `uvicorn muse_bot.server:app --port 8000`.

### Muse OS on a VPS

Any small Linux VPS with Docker (Hetzner, DigitalOcean, Linode, about $5–6/month), ports 80 and 443 open, and a DNS A record (e.g. `os.musehospitality.com`) pointing at it.

```
curl -fsSL https://get.docker.com | sh          # once
# copy muse-os/ (or muse-os.zip) to the server
cd muse-os && cp .env.example .env && nano .env  # DOMAIN=...
docker compose up -d --build
docker compose exec app python -m app.cli create-admin devin   # prints a temporary password
```

- Services (`docker-compose.yml`): `app` (uvicorn on 8000, non-root user, healthcheck `/healthz`), Traefik labels on `app` (router `muse-os`, `X-Robots-Tag: noindex` middleware; `TRAEFIK_*` in `.env`), `backup` (nightly copies).
- Volume: `muse-data` (the SQLite DB). Data survives `docker compose up -d --build`.
- **Update:** copy the new code over, then `docker compose up -d --build`. Schema changes are applied on start (`CREATE TABLE IF NOT EXISTS` plus additive migrations in `app/db.py`).
- CLI (`python -m app.cli`): `create-admin`, `reset-password`, `create-api-key`, `backup <dest.db>`, `backup-loop <dir> [days]`.
- **Per-person view settings:** each user can hide table columns and weekdays (stored per account in `user_prefs`, so they follow the person across devices). Weekly setup and Tonight respect hidden days; saving Weekly setup leaves hidden days untouched.
- **Engineer role (Team page):** a Team role used for paying the engineer. A new Engineer row defaults to *Monthly flat* $50, and payouts go to the Ledger as *Engineer payout*. It's a pay role, not a login role. To give the engineer access to the app itself, create an **Admin** login for them.
- Logins: admins create a user in **Admin > Logins** (`/admin/users`) and send a one-time link (valid 7 days) for the person to pick their own password. Admins never see passwords.
- Security already in place: scrypt password hashes, hashed session tokens in HttpOnly/Secure/SameSite cookies, CSRF on every form, login rate limit (8 failures per 15 min per IP and per username), strict CSP, HSTS, no framing, audit log of every change.

### Backups

- **Muse OS:** the `backup` container takes a consistent SQLite copy (SQLite backup API) every 24 h to `./backups/muse-YYYY-MM-DD.db` on the host and keeps 30. **These live on the same server.** Please add an off-site copy (e.g. nightly rsync or rclone to S3/B2), because losing the VPS loses the backups too. Restore: `docker compose stop app`, copy a backup over `/data/muse.db` in the `muse-data` volume, start again.
- **DM bot:** `/data/muse_leads.db` on the Render disk holds conversation state, the stored token, and the remembered Graph host. Once Muse OS is connected, leads and bookings are mirrored there, so this DB matters mainly for in-flight conversations. Check Render's disk snapshot settings for the service, and export `/leads.csv` occasionally if you want an extra copy.

---

## 7. Bot business rules

Everything the bot says lives in `muse-dm-bot/config.yaml`. Muse OS overrides most venue data once connected. Precedence for per-night values (dress code, cover, ticket link, list close time): **Weekly setup night value > Muse OS venue value > `config.yaml`**.

### Conversation flow
- One question per message, like a person texting: night → venue (skipped if only one is on) → party size → any guys (then how many) → "Is everyone over 21? Only physical IDs are accepted" → confirmation. If a guest answers several things at once, the bot keeps them all and skips ahead.
- Questions get a direct answer first, then the next question (girls free with table and drinks, guys' price, timing, dress code, bringing friends, 21+, how it works, which venues this week).
- Voice: a young, social girl texting friends. Short, warm, casual ("ofc", "yay"), no corporate phrasing, no long dashes. Greeting is "Hi!". The only emoji is the 💕 at the end of the confirmation.
- Hosts are named by **first name only** in messages to guests (`host_for()` trims the lineup name), so an employee's full name is never sent.
- If a reply answers nothing, the bot asks the single missing question; if the next reply still doesn't, it hands off instead of looping.
- "Not this weekend" gets "No worries! We'll invite you again soon".
- After midnight, anything before 5am counts as the previous night.

### Venues
The current list: Nebula, Public Hotel, NOFLEX, Den Social, Marquee, NYX Karaoke, PHD Rooftop, Petite Disco, Highlight Room, Loosies, Slate, Maru. Muse OS starts with four venues and pay terms (Public Hotel, Den Social, Nebula, NOFLEX); the rest are added on the Venues page.

- **Only Nebula's details are confirmed** (host Devin, arrive at 11, list closes 1:30am, dress code "Heels or leather boots are recommended (please try to avoid sneakers or Uggs)", guys need a ticket, Fri/Sat). Everything marked `TODO` in `config.yaml` (host, arrival time, dress code for the other venues) is a guess.
- **Schedule:** the bot offers only nights on the dated lineup from Muse OS Weekly setup. The weekly pattern (Muse OS venue "nights", or `config.yaml` `schedule`) only fills in nights past what's posted. Fallback pattern: Thu Public Hotel + NOFLEX, Fri NOFLEX + Nebula, Sat NYX Karaoke + Nebula.
- Asking for a venue on a night Muse isn't there gets "We're not at {venue} {night}", the venue's next nights, and what is on that night.
- **A venue Muse doesn't work with** (e.g. "i wanna go to mission"), or "can we go somewhere else": **silent handoff**. The bot doesn't reply, marks the lead *Needs a human*, alerts the team, and stays quiet in that chat.

### Guys policy
Set per venue in Muse OS (*Guys' entry*: Ticket / Cover at the door / Free / Ask the team), with a **per-night override on Weekly setup** (sent to the bot as `venues[].upcoming[].guys_policy`; blank = the venue's usual). Fallback: `guys_policy` in config (`ticket`, `ok`/`free`, `ratio`, `ask`, `cover`, `no`). Precedence: night > venue > config.
- **Ticket** (default everywhere except Marquee and NOFLEX): the confirmation adds "Guys just need a ticket ($cover): {link}". Links change weekly; supervisors send them by Monday morning. Nebula has separate Friday and Saturday links (per-night link on Weekly setup). Missing link: guests are told the link will follow, and the team is alerted. Monday at noon the team gets a list of venue nights running that week with no link.
- **Cover at the door** (NOFLEX): "The guys just pay a {cover} cover at the door, they don't need a ticket." The price comes from the "Cover this night" box on Weekly setup, filled in every Sunday. No link and no missing-link alert; instead, Monday at noon the team is alerted about cover-only nights that week with no price.
- **Free:** "Guys get in free too, no ticket needed." A night's cover entered as free or $0 is treated the same way. No link and no missing-link alert.
- **Ask** (Marquee, strict door): hand off to the team ("let me check with the door").
- **Table rule (`guys_at_table: one`), Nebula and NOFLEX:** with 2 or more guys the confirmation adds "Heads up, the guys can't be at the table, but you can bring them drinks from it". A single guy can sit at the table.

### Dress codes
Per night from Weekly setup > venue's per-weekday dress code in config > venue default. A venue confirmation message in Muse OS can include `[DRESS_CODE]` and `[HOST]`.

### Guestlist close times
- Per venue (`list_closes`, Muse OS Venues page "Guestlist closes") with a per-night override on Weekly setup. Default if unset: **00:30**. Nebula: **01:30**. Times after midnight belong to the night before.
- Asking for tonight only offers venues whose list is still open. For a closed venue: "The list for {venue} {night} closed at {time}" plus what's still open, or the venue's next nights.
- From 23:30 (`late_after`) to close: "head over now, the list closes at {time}". After close: no confirmation; "let me check if we can still get you in" plus a team alert.

### Hand-offs to a human (team alert, bot steps back)
Birthdays and bachelorettes, buying tables or bottles, discounts and promo codes, complaints, job inquiries, sign requests (no standard answer yet), anyone under 21 or without a physical ID (e.g. "20yr olds", "we are 19"), groups over 15 people or over 15 guys (`big_group`), guests who aren't sure yet how many are coming ("idk", "not sure yet" when asked for the group size or number of guys: "Someone from the team will check in with you to sort out your group"), guys at "ask" venues, questions it can't answer, and venues Muse doesn't work with.

### Other behaviour
- **Human takeover:** if anyone replies from the Instagram app, the bot goes quiet in that chat for **10 minutes** (`human_takeover_minutes`), restarting with each message the promoter sends. If the girl double-texts (2 messages with no promoter reply in between) and the bot can actually answer, the hold-off ends early and the bot picks the chat back up; otherwise it stays quiet. While quiet it keeps logging what the guest says (night, venue, group size) to the lead. `POST /guests/{ig_user_id}/resume` turns it back on.
- **Scouts:** a DM naming a scout's @handle or full name, or their first name near "sent me / from / told me", tags the lead's *Referred by*. Scouts earn their rate (default $5) per arrived girl, only at per-girl venues and only on her first night in (Muse OS `calc.py`).
- **Arrival:** "we're here / outside / in line" sends "{host} is coming out to grab you" and alerts the host. "otw" gets a text-us-when-outside reply.
- **Follow-ups at 13:00 next day:** thank-you if arrived, "we missed you" if a no-show (only inside the 24-hour window).
- **9pm digest:** each venue's list for tonight, under that night's host. Bookings after 9pm send a "Late add" alert.

---

## 8. Known issues and open items

**Needs an answer from the owner**
1. **Which venue closes its guestlist at 8pm?** Mentioned as an example but never named. Set it on the Muse OS Venues page ("Guestlist closes") once known.
2. **Venue details other than Nebula** (host, arrival time, dress code) are guesses marked `TODO` in `config.yaml`. Confirm them in Muse OS.
3. **Each venue's usual guys' entry** (Ticket, Cover, Free or Ask) should be set on the Muse OS Venues page. In `config.yaml` every venue except Marquee and NOFLEX (cover) is "ticket".
4. **Standard answer for sign requests** (free with bottles? cost? which venues?). Currently handed off.
5. **Manual outreach:** when the team DMs a girl first from the Muse account, the bot now holds off only 10 minutes (and less if she double-texts), so in practice it picks up her reply. Confirm with the owner that this is the behaviour they want.

**Needs engineering**
6. **App Review for non-testers.** The app was published on 2026-11-10, but it's unconfirmed whether non-testers get replies. Test with a non-tester account. If they don't, request Advanced Access for `instagram_business_basic` and `instagram_business_manage_messages` (privacy URL is `/privacy`; submit a screen recording of a bot conversation).
7. **Token renewal is manual under Unified login.** The bot warns daily from 10 days before expiry (section 5), but someone has to generate a new token and paste it into `IG_ACCESS_TOKEN`. Make sure `NOTIFY_WEBHOOK_URL` is set (item 11) so the warning actually reaches a person.
8. **GitHub vs Library drift.** Make sure the repo matches `muse-dm-bot/` in the Library (section 6), then switch to git-based deploys.
9. **Muse OS not deployed yet** (as far as we know). Once it is, do section 3 and fill in Weekly setup.
10. **Off-site backups** for Muse OS (section 6).
11. **`NOTIFY_WEBHOOK_URL`** may be unset. Without it, every team alert (handoffs, arrivals, missing links, digest) only goes to logs.
12. **Alerts go to one team channel.** Per-host pings (their own Slack/Discord handle or SMS) are a possible extension.
13. **One host per venue per night** on the lineup. Two promoters at the same venue: only the listed one is named.
14. **The bot README is partly stale:** it still mentions the ManyChat interim path, the "Hiii" greeting and 125 tests. The behaviour in this document is current.
15. **iMessage is not integrated** (Apple has no API). Texted guests and walk-ups are added by hand (+ New lead, or Walk-up on Tonight). A business number such as Twilio is the option if volume warrants it.
16. **Only one tool can answer the account's DMs.** If ManyChat was ever connected, make sure it's off.

---

## 9. Where things are

| Item | Location |
|---|---|
| Bot code and config | Library `muse-dm-bot/` (`config.yaml`, `muse_bot/engine.py` flow, `parser.py` message reading, `server.py` webhook/jobs/team links, `store.py` SQLite, `museos.py` sync, `reports.py`) |
| Bot edge-case transcripts | Library `muse-dm-bot-tests/edge-cases.md` |
| Training data from DM history | Library `dm-analysis/training/` |
| Muse OS code | Library `muse-os/` (`app/main.py` pages, `app/api.py` bot API, `app/calc.py` money rules, `app/db.py` schema, `app/admin.py` admin and Weekly setup, `app/cli.py`) |
| Muse OS screenshots | Library `muse-os-screens/` |
| Muse OS deploy bundle | Library `muse-os.zip` |
