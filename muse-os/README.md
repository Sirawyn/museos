# Muse OS

Muse Hospitality's private web app for running nights: DMs, guests, bookings, the door, venues, team pay and money. Every promoter, host, social rep and scout gets their own login
and sees only what their role allows. It works on a phone at the door.

## What's in it

| Tab | What it does |
|---|---|
| Dashboard | Admins: the whole business for any week (funnel, reply speed, venues against quota, money for the month, team, scouts, guest base, top posts and format scoreboard). Everyone else gets a personal home page with their own numbers and pay. |
| Tonight | The door list for a night, filtered by venue, with tap-to-check-in: set how many girls got in, then Arrived or No-show. No-show-risk and VIP guests are tagged. Before 6am it still shows last night. Admins also see the week's lineup. |
| Weekly setup | Admins, once a week (Sunday): one form for the coming week's lineup (which venues run each night and the host on duty) and the guys' ticket link per venue. Usual nights are pre-ticked with last week's host; stale links are highlighted. The DM bot reads all of it through `GET /api/v1/venues`. |
| Social | For the social media managers and the founder. **Social hub**: follower goal (10k by Dec 15) with pace, the founder's approval queue, this week's board (To make, In review, Ready to post, Posted) with one-tap status moves, each manager's weekly quota (3 Reels + 1 carousel), Reels over 100k views this month, campaigns with progress, next shoot nights, top ideas, and a link to the UGC creator tracker. **Calendar**: month view of planned posts, shoot nights and campaign start/end, filter by person or campaign. **Content plan, Campaigns, Idea backlog, Shoot nights, Follower log** tabs. Posts marked "Needs founder approval" (new formats, series, collabs) can't be approved, scheduled or posted until an admin approves them; marking a post Posted logs it on Content automatically so its views and DMs are tracked. Ideas move onto the calendar in one tap. Targets live in Admin settings (`follower_goal`, `weekly_reels`, ...). |
| Leads, Guests, Bookings, Nights, Venues, Team, Content, Ledger | Everything you track, one page each. The calculated numbers (reply time, tier, revenue, door pay, balances, quota %, engagement, DMs per post…) are worked out by the app. Search, filters and CSV export (admins). |

### The money rules (app/calc.py)
* **Flat per night**: the venue's flat rate, or the night's override (Public Hotel $150, Den Social $100).
* **Per guest (capped)**: girls arrived × rate, up to the cap (Nebula $12 per girl, $180 cap = 15 girls).
* **Per guest (uncapped)**: girls arrived × rate (NOFLEX $10).
* Plus **table/bottle commission**: table spend × the venue's commission %.
* Girls counted = the host's arrived count, or the booked girls if no count was entered. Only Arrived bookings count.
* **Hosts and promoters** are paid by their Team pay type: per guest arrived, per night worked, or monthly flat.
* **Scouts** earn their rate (default $5) per arrived girl they referred, **only for first-time girls and only at per-girl venues**. A girl is first-time on her earliest booking that got in; later visits pay no scout, even if someone tags them again. A scout on
  the booking overrides the one on the lead.
* **No-show risk**: 2 or more played bookings with a no-show rate at or above 34%. **Muse VIP**: 5+ nights out.
  Both thresholds are in Admin > Settings.

### Who sees what
| Role | Sees |
|---|---|
| Admin | Everything, including revenue, venue pay terms, payouts and the Ledger. Manages logins and API keys. Only admins can delete. |
| Host, Promoter | Tonight's routing and check-in, plus the Leads, Bookings and Guests that are theirs: they're the assigned host, or the host on duty at that venue that night (Nights tab). Venue door info (dress code, arrive by, men policy, confirmation message). Their own pay. No revenue, commission, table spend or venue pay terms. New leads and bookings they add are always under their own name. |
| Social media | Social (hub, calendar, content plan, campaigns, ideas, shoots, follower log), Content (add and edit posts), the format scoreboard, venue door info. Can't approve posts. No guest data. |
| Scout | Only their own referrals and earnings. |

### Security
* Passwords hashed with scrypt. Everyone sets their own password from a one-time login link (10+ characters);
  admins never see or send passwords.
* Sessions are random tokens in an HttpOnly, Secure, SameSite cookie; only a hash is stored. 30-day sessions;
  changing a password, a role, or turning a login off signs that person out everywhere.
* Every form is CSRF-protected. Logins are rate limited (8 failures per 15 minutes per IP and per username).
* Strict Content-Security-Policy, no framing, no caching of pages, HSTS, `noindex`.
* Every change is written to the change log (Admin > Change log) with who made it.
* The DM bot uses its own API key (hashed, revocable), which can't read money, the Ledger or logins.
* Nightly database backups, 30 days kept.

## Deploy (Docker, behind Traefik)

You need a small Linux server (any $5–6/month VPS from Hetzner, DigitalOcean, Linode or similar) with Docker, and a
domain or subdomain (e.g. `os.musehospitality.com`).

1. Point the domain's DNS (an A record) at the server's IP.
2. Copy this folder to the server, then:
   ```
   cp .env.example .env          # set DOMAIN and the TRAEFIK_* names
   docker compose up -d --build
   docker compose exec app python -m app.cli create-admin devin
   ```
   Traefik picks it up and gets the HTTPS certificate on its own. Open `https://your.domain`, log in with the temporary password it
   printed, and choose your own.
3. A new install starts with your four venues and their pay terms (Public Hotel, Den Social, Nebula, NOFLEX).
   Add the rest on Venues, your people on Team, and this week's lineup on Nights.
4. Add a login for each person in Settings > Logins and link it to their Team row. You get a personal login link
   (one-time, 7 days) with a ready-to-send text; they open it, choose their own password and land on their own
   home page. Forgot password: "Send new link" on the same page.
5. Connect the DM bot: Admin > DM bot API > Create key, then set `MUSE_OS_URL` and `MUSE_OS_API_KEY` on the bot.

On a phone, open the site and use "Add to Home Screen" so it opens like an app.

Updating: copy the new code over, then `docker compose up -d --build`. Data lives in the `muse-data` volume and
survives updates. Backups are in `./backups`; to restore, stop the app and copy a backup over `/data/muse.db`.

Trying it on a laptop without a domain:
```
pip install -r requirements.txt
MUSE_INSECURE_COOKIES=1 MUSE_DB=data/muse.db python -m app.cli create-admin devin
MUSE_INSECURE_COOKIES=1 MUSE_DB=data/muse.db uvicorn app.main:app --port 8000
```

## Card Instagrams (Muse NFC cards)
Admins get a **Card Instagrams** page (sidebar under Admin, or More on a phone). It lists every Instagram the Muse cards
collected (tap.musehospitality.social, the separate muse-cards app): girls who claimed a card and friends who sent their
Instagram from someone's card, who referred them, when, and whether she's already a guest or lead here. It has a CSV button.
Muse OS doesn't copy the list. It reads it live from the cards app each time the page opens.

Connect it in `.env`, then `docker compose up -d`:
```
CARDS_URL=http://muse-cards:8000      # cards app on the shared Traefik network
CARDS_TOKEN=<the cards app's ADMIN_TOKEN>
```
If the cards app runs on its own instead, use `CARDS_URL=https://tap.musehospitality.social`.

## DM bot API

Auth: `Authorization: Bearer <key>`. All bodies are JSON; unknown fields are rejected.

| | |
|---|---|
| `PUT /api/v1/leads/{lead_id}` | Create or update a lead (`DM-00001` style ids). Fields: created_at, channel, ig_handle, name, night, venue, party_size, girls, guys, status, host, first_reply_at, source_content_id, last_message_at, notes, referred_by. Also adds the guest if new. A host's Arrived/No-show is never downgraded. |
| `PUT /api/v1/guests/{ig_handle}` | Add a guest. An existing guest is left alone so tags and notes stay. |
| `PUT /api/v1/bookings/{booking_id}` | Create or update a booking (night, venue, ig_handle required). On create, the host is the Nights tab's host on duty for that venue night when one is set (else the host sent); after that the bot doesn't change the host. Once a host has checked it in at the door, the bot can't overwrite its status or count. |
| `GET /api/v1/venues` | Each venue's nights we run, confirmation message, guys' ticket link, arrive by, dress code, men policy, `upcoming`: `[{"night": "YYYY-MM-DD", "host": "Mia" or null}]` for the next 14 lineup nights. No pay terms. |
| `GET /api/v1/scouts` | Active scouts (name, handle). |
| `GET /api/v1/checkins?since=…` | Bookings checked in, marked no-show, or undone at the door since the last call (pass back the previous `now`), so the bot sends the right thank-you or "we missed you". |

`integrations/museos.py` is the bot's client for this API (the DM bot already uses it).

## Development
```
pip install -r requirements.txt pytest httpx
python -m pytest -q tests
```
