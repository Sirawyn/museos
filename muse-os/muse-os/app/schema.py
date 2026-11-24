"""Every page of Muse OS as an entity: its fields, labels, dropdown choices, and which fields are money
(admin only)."""
from __future__ import annotations

from dataclasses import dataclass, field

LEAD_STATUS = ["New", "Qualifying", "Qualified", "Confirmed", "Arrived", "No-show", "Lost"]
BOOKING_STATUS = ["Confirmed", "Arrived", "No-show", "Cancelled"]
PAY_MODELS = ["Per guest (uncapped)", "Per guest (capped)", "Flat per night"]
PER_GIRL_MODELS = ("Per guest (uncapped)", "Per guest (capped)")
VENUE_STATUS = ["Active", "Paused", "Prospect"]
GUYS_POLICY = ["Ticket", "Cover at the door", "Free", "Ask the team"]
MEN_POLICY = ["Girls only", "Men with girls only", "Men welcome"]
TEAM_ROLES = ["Administrator", "Host", "Promoter", "Social Media", "Scout", "Engineer"]
PAY_TYPES = ["Per guest", "Per night", "Monthly flat", "Per girl referred"]
TEAM_STATUS = ["Active", "Training", "Inactive"]
CHANNELS = ["Instagram", "TikTok", "LinkedIn", "Referral", "Text", "Other"]
CONTENT_FORMATS = ["Weekly lineup", "Education", "Street interview", "Relatability", "Photo spots", "UGC",
                   "Night recap", "Other"]
LEDGER_TYPES = ["Venue payment", "Other income", "Host payout", "Social payout", "Expense",
                "Table/bottle commission", "Scout payout", "Engineer payout"]
PAYMENT_STATUS = ["Paid", "Pending"]
INCOME_TYPES = ("Venue payment", "Other income", "Table/bottle commission")


@dataclass
class Field:
    name: str
    label: str
    type: str = "text"   # text|longtext|int|money|pct|date|datetime|time|choice|bool|venue|team|url
    choices: list[str] | None = None
    money: bool = False         # hidden from everyone but admins
    required: bool = False
    aliases: tuple[str, ...] = ()
    list: bool = True           # shown in the list view
    team_role: str | None = None  # restrict team dropdown (e.g. Scout)
    help: str = ""


@dataclass
class Entity:
    slug: str
    title: str
    table: str
    pk: str
    fields: list[Field]
    id_prefix: str | None = None   # generated text ids, e.g. L-00001
    order: str = ""
    search: tuple[str, ...] = ()
    singular: str = ""
    computed: list[tuple[str, str, bool]] = field(default_factory=list)  # (key, label, money)

    def f(self, name: str) -> Field:
        return next(x for x in self.fields if x.name == name)


ENTITIES: dict[str, Entity] = {}


def _add(e: Entity) -> Entity:
    ENTITIES[e.slug] = e
    return e


LEADS = _add(Entity("leads", "Leads", "leads", "id", [
    Field("id", "Lead ID", list=False),
    Field("created_at", "Created at", "datetime"),
    Field("channel", "Channel", "choice", CHANNELS),
    Field("ig_handle", "IG handle", required=True),
    Field("name", "Name"),
    Field("night", "Requested night", "date"),
    Field("venue", "Venue requested", "venue", aliases=("Venue",)),
    Field("party_size", "Party size", "int"),
    Field("girls", "Girls", "int"),
    Field("guys", "Guys", "int"),
    Field("status", "Status", "choice", LEAD_STATUS),
    Field("host", "Assigned host", "team"),
    Field("first_reply_at", "First reply at", "datetime", list=False),
    Field("source_content_id", "Source content ID", list=False),
    Field("last_message_at", "Last message at", "datetime", list=False),
    Field("notes", "Notes", "longtext", list=False),
    Field("referred_by", "Referred by (scout)", "team", team_role="Scout", list=False),
], id_prefix="L-", order="created_at DESC", search=("id", "ig_handle", "name", "notes"), singular="lead",
    computed=[("reply_min", "Reply time (min)", False), ("guests_arrived", "Guests arrived", False),
              ("revenue", "Revenue est. ($)", True), ("tier", "Guest tier", False)]))

GUESTS = _add(Entity("guests", "Guests", "guests", "ig_handle", [
    Field("ig_handle", "IG handle", required=True),
    Field("name", "Name"),
    Field("phone", "Phone", list=False),
    Field("first_contact", "First contact", "date", list=False),
    Field("first_channel", "First channel", "choice", CHANNELS, list=False),
    Field("first_content_id", "First content ID", list=False),
    Field("tags", "Tags"),
    Field("notes", "Notes", "longtext", list=False),
], order="ig_handle", search=("ig_handle", "name", "tags", "notes", "phone"), singular="guest",
    computed=[("bookings", "Bookings", False), ("nights_out", "Nights out", False), ("no_shows", "No-shows", False),
              ("no_show_rate", "No-show rate", False), ("last_night_out", "Last night out", False),
              ("tier", "Tier", False)]))

BOOKINGS = _add(Entity("bookings", "Bookings", "bookings", "id", [
    Field("id", "Booking ID", list=False),
    Field("night", "Night", "date", required=True),
    Field("venue", "Venue", "venue", required=True),
    Field("ig_handle", "IG handle", required=True),
    Field("lead_id", "Lead ID", list=False),
    Field("host", "Host", "team"),
    Field("stop", "Stop #", "int"),
    Field("party_size", "Party size", "int"),
    Field("girls", "Girls", "int"),
    Field("guys", "Guys", "int"),
    Field("status", "Status", "choice", BOOKING_STATUS),
    Field("girls_arrived", "Girls arrived", "int"),
    Field("confirmation_sent", "Confirmation sent", "bool", list=False),
    Field("thank_you_sent", "Thank-you sent", "bool", list=False),
    Field("notes", "Notes", "longtext", list=False),
    Field("table_spend", "Table/bottle spend ($)", "money", money=True, list=False),
    Field("referred_by", "Referred by (scout)", "team", team_role="Scout", list=False,
          help="Overrides the lead's scout"),
], id_prefix="BK-", order="night DESC, ig_handle, stop", search=("id", "ig_handle", "notes", "lead_id"),
    singular="booking",
    computed=[("girls_counted", "Girls counted", False), ("revenue", "Revenue est. ($)", True),
              ("commission", "Commission est. ($)", True), ("scout", "Scout credited", False)]))

NIGHTS = _add(Entity("nights", "Nights", "nights", "id", [
    Field("night", "Night", "date", required=True),
    Field("venue", "Venue", "venue", required=True),
    Field("host", "Host on duty", "team"),
    Field("dress_code", "Dress code this night", list=False, help="Leave blank to use the venue's dress code"),
    Field("cover", "Guys' cover this night", list=False, help='Free text, e.g. "$40" or "$30 before 12"'),
    Field("guys_policy", "Guys' entry this night", "choice", GUYS_POLICY, list=False,
          help="Leave blank to use the venue's usual setting"),
    Field("list_closes", "Guestlist closes this night", "time", list=False,
          help="Leave blank to use the venue's usual closing time"),
    Field("ticket_link", "Guys' ticket link this night", "url", list=False,
          help="Only if this night has its own link; otherwise the venue's link is used"),
    Field("notes", "Notes", "longtext", list=False),
    Field("flat_override", "Flat rate this night ($, if different)", "money", money=True, list=False),
], order="night DESC, venue", search=("venue", "host", "notes"), singular="night",
    computed=[("girls_confirmed", "Girls confirmed", False), ("girls_arrived", "Girls arrived", False),
              ("show_rate", "Show rate", False), ("pay_model", "Pay model", True), ("door_pay", "Door pay ($)", True),
              ("commission", "Table/bottle commission ($)", True), ("total", "Total earned ($)", True)]))

VENUES = _add(Entity("venues", "Venues", "venues", "id", [
    Field("name", "Venue", required=True),
    Field("neighborhood", "Neighborhood"),
    Field("nights", "Nights we run", help="e.g. Thursday, Friday. The DM bot offers the venue on these nights."),
    Field("pay_model", "Pay model", "choice", PAY_MODELS, money=True),
    Field("rate_per_guest", "Rate per guest ($)", "money", money=True),
    Field("cap_per_night", "Cap per night ($)", "money", money=True,
          help="Per guest (capped) only. Nebula: $12 x 15 girls = $180"),
    Field("flat_rate", "Flat rate per night ($)", "money", money=True),
    Field("weekly_quota", "Weekly guest quota", "int"),
    Field("men_policy", "Men policy", "choice", MEN_POLICY),
    Field("guys_policy", "Guys' entry", "choice", GUYS_POLICY, list=False,
          help="How guys usually get in: buy a ticket, pay cover at the door, free, or ask the team. Weekly setup can change it for one night."),
    Field("dress_code", "Dress code (usual)", list=False,
          help="Used when a night has no dress code of its own (set those in Weekly setup)"),
    Field("arrive_by", "Arrive by", "time"),
    Field("list_closes", "Guestlist closes", "time",
          help="Usual closing time for the list, e.g. 20:00, or 01:30 for after midnight"),
    Field("confirmation_message", "Confirmation message", "longtext", list=False,
          help="[HOST] becomes the host on duty and [DRESS_CODE] that night's dress code"),
    Field("contact", "Venue contact", list=False, money=True),
    Field("status", "Status", "choice", VENUE_STATUS),
    Field("ticket_link", "Guys ticket link (update Mondays)", "url", list=False, aliases=("Ticket link",),
          help="Used for any night that doesn't have its own link in Weekly setup"),
    Field("commission_pct", "Table/bottle commission %", "pct", money=True, list=False),
], order="status, name", search=("name", "neighborhood"), singular="venue",
    computed=[("girls_week", "Girls this week", False), ("quota_pct", "Quota hit %", False),
              ("earned", "Revenue earned to date ($)", True), ("received", "Cash received ($)", True),
              ("owed", "Owed by venue ($)", True)]))

TEAM = _add(Entity("team", "Team", "team", "id", [
    Field("name", "Name", required=True),
    Field("role", "Role", "choice", TEAM_ROLES),
    Field("ig_handle", "IG handle"),
    Field("phone", "Phone", list=False),
    Field("home_venue", "Home venue", "venue", list=False),
    Field("pay_type", "Pay type", "choice", PAY_TYPES),
    Field("pay_rate", "Pay rate ($)", "money"),
    Field("status", "Status", "choice", TEAM_STATUS),
    Field("start_date", "Start date", "date", list=False),
], order="status, role, name", search=("name", "ig_handle", "role"), singular="team member",
    computed=[("girls_confirmed", "Girls confirmed", False), ("girls_arrived", "Girls arrived", False),
              ("show_rate", "Show rate", False), ("nights_worked", "Nights worked", False),
              ("leads_handled", "Leads handled", False), ("earned", "Earned ($)", True), ("paid", "Paid ($)", True),
              ("balance", "Balance owed ($)", True), ("referred", "Girls referred (arrived)", False)]))

CONTENT = _add(Entity("content", "Content", "content", "post_id", [
    Field("post_id", "Post ID", required=True),
    Field("date_posted", "Date posted", "date"),
    Field("platform", "Platform", "choice", CHANNELS),
    Field("format", "Format", "choice", CONTENT_FORMATS),
    Field("hook", "Hook or title"),
    Field("creator", "Creator", "team"),
    Field("link", "Link", "url", list=False),
    Field("views", "Views", "int"),
    Field("likes", "Likes", "int", list=False),
    Field("comments", "Comments", "int", list=False),
    Field("shares", "Shares", "int", list=False),
    Field("saves", "Saves", "int", list=False),
    Field("new_follows", "New follows", "int", list=False),
], order="date_posted DESC", search=("post_id", "hook", "creator"), singular="post",
    computed=[("engagement", "Engagement rate", False), ("dms", "DMs", False), ("girls_out", "Muse Girls out", False),
              ("revenue", "Revenue est. ($)", True), ("dms_per_10k", "DMs per 10k views", False)]))

LEDGER = _add(Entity("ledger", "Ledger", "ledger", "id", [
    Field("date", "Date", "date", required=True),
    Field("type", "Type", "choice", LEDGER_TYPES, required=True),
    Field("venue", "Venue", "venue"),
    Field("person", "Person", "team"),
    Field("amount", "Amount ($)", "money", required=True),
    Field("status", "Status", "choice", PAYMENT_STATUS),
    Field("method", "Method"),
    Field("covers", "Covers"),
    Field("notes", "Notes", "longtext", list=False),
], order="date DESC, id DESC", search=("venue", "person", "covers", "notes", "method"), singular="ledger entry",
    computed=[("signed", "Signed amount ($)", True), ("month", "Month", False)]))

# ---------- Social: planning the content (calendar, campaigns, idea backlog, shoots, follower log) ----------
POST_FORMATS = ["Reel", "Carousel", "Collab Reel", "Single photo", "Story set", "TikTok repost"]
PILLARS = ["Muse 101", "The Girls", "It's So Real", "The Night", "Behind Muse"]
PLAN_STATUS = ["Planned", "Filming", "Editing", "Ready for review", "Approved", "Scheduled", "Posted", "Skipped"]
# Statuses a post can only reach after the founder approves it, when it needs approval
NEEDS_OK = ("Approved", "Scheduled", "Posted")
CAMPAIGN_STATUS = ["Planned", "Active", "Unconfirmed", "Done", "Cancelled"]
IDEA_STATUS = ["New", "Shortlisted", "On the calendar", "Parked"]
PRIORITY = ["High", "Medium", "Low"]
SHOOT_STATUS = ["Planned", "Shot", "Filed"]

PLAN = _add(Entity("plan", "Content plan", "plan", "id", [
    Field("id", "Plan ID", list=False),
    Field("planned_date", "Post date", "date", required=True),
    Field("planned_time", "Post time", "time", list=False, help="NYC time. Weekdays 12-1pm or 7-10pm; Thu/Fri 5-8pm for same-night DMs"),
    Field("title", "Working title", required=True),
    Field("format", "Format", "choice", POST_FORMATS, required=True),
    Field("pillar", "Pillar", "choice", PILLARS),
    Field("campaign", "Campaign", "campaign"),
    Field("owner", "Owner", "team"),
    Field("status", "Status", "choice", PLAN_STATUS),
    Field("needs_approval", "Needs founder approval (new format, series or collab)", "bool", list=False),
    Field("hook", "Hook (first 2 seconds)", list=False),
    Field("caption", "Caption", "longtext", list=False),
    Field("cta", "DM ask / keyword", list=False, help='e.g. DM us LIST, DM us MUSE, DM us FIRSTTIME'),
    Field("shot_list", "Shots needed / script", "longtext", list=False),
    Field("asset_link", "Footage or edit link", "url", list=False, help="Drive folder, CapCut export, etc."),
    Field("brief_link", "Script or brief link", "url", list=False),
    Field("content_type", "Content type (for the scoreboard)", "choice", CONTENT_FORMATS, list=False),
    Field("post_link", "Instagram link once posted", "url", list=False),
    Field("post_id", "Content post ID", list=False, help="Filled in for you when it's marked Posted"),
    Field("review_note", "Founder's note", "longtext", list=False),
    Field("notes", "Notes", "longtext", list=False),
], id_prefix="P-", order="planned_date, planned_time, id", search=("id", "title", "hook", "caption", "campaign", "owner", "notes"),
    singular="planned post",
    computed=[("approval", "Approval", False), ("views", "Views", False), ("dms", "DMs", False)]))

CAMPAIGNS = _add(Entity("campaigns", "Campaigns", "campaigns", "id", [
    Field("name", "Campaign", required=True),
    Field("start_date", "Starts", "date"),
    Field("end_date", "Ends", "date"),
    Field("status", "Status", "choice", CAMPAIGN_STATUS),
    Field("owner", "Lead", "team"),
    Field("goal", "Goal", "longtext", list=False),
    Field("keyword", "DM keyword", list=False),
    Field("hashtags", "Hashtags", list=False),
    Field("brief_link", "Brief or doc link", "url", list=False),
    Field("notes", "Notes", "longtext", list=False),
], order="status='Done', start_date, name", search=("name", "goal", "notes"), singular="campaign",
    computed=[("posts", "Posts planned", False), ("posted", "Posted", False), ("progress", "Done", False),
              ("views", "Views", False), ("dms", "DMs", False)]))

IDEAS = _add(Entity("ideas", "Idea backlog", "ideas", "id", [
    Field("id", "Idea ID", list=False),
    Field("title", "Idea", required=True),
    Field("format", "Format", "choice", POST_FORMATS),
    Field("pillar", "Pillar", "choice", PILLARS),
    Field("campaign", "Campaign", "campaign", list=False),
    Field("priority", "Priority", "choice", PRIORITY),
    Field("status", "Status", "choice", IDEA_STATUS),
    Field("new_format", "New format (needs founder approval)", "bool", list=False),
    Field("added_by", "Added by", "team"),
    Field("details", "Details", "longtext", list=False),
    Field("example_link", "Example / reference link", "url", list=False),
    Field("plan_id", "Plan ID", list=False, help="Set when the idea is moved onto the calendar"),
], id_prefix="I-", order="status IN ('On the calendar','Parked'), CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END, id",
    search=("id", "title", "details", "added_by"), singular="idea"))

SHOOTS = _add(Entity("shoots", "Shoot nights", "shoots", "id", [
    Field("date", "Night", "date", required=True),
    Field("venue", "Venue", "venue"),
    Field("who", "Who's filming", "team"),
    Field("status", "Status", "choice", SHOOT_STATUS),
    Field("shot_list", "Shot list", "longtext", list=False),
    Field("questions", "Street interview questions", "longtext", list=False),
    Field("footage_link", "Footage folder", "url", list=False),
    Field("notes", "Notes", "longtext", list=False),
], order="date DESC", search=("venue", "who", "notes"), singular="shoot night"))

GROWTH = _add(Entity("growth", "Follower log", "growth", "id", [
    Field("date", "Date", "date", required=True),
    Field("followers", "Instagram followers", "int", required=True),
    Field("notes", "Notes", "text"),
], order="date DESC", search=("notes",), singular="follower count",
    computed=[("change", "Change since last", False)]))
