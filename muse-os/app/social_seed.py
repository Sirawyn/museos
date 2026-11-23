"""Starting content for the social planner (runs once per database, 2026-11-17).

Campaigns and posts come from the Social Strategy handbook (Going Out With Muse, the Monday recap) and the
"Why we made Thalia" content series doc. Everything can be edited or deleted afterwards.
"""
from __future__ import annotations

THALIA_DOC = "https://claude.ai/artifact/Yb1HkEqYrQA6dG1s141hz7"

CAMPAIGNS = [
    # name, start, end, status, goal, keyword, hashtags, brief link, notes
    ("Going Out With Muse", "2026-11-19", "2026-12-13", "Active",
     "4-week UGC campaign through Thanksgiving Eve. 3 creators, 12 paid videos (4 each), median 5,000+ views at day 7, "
     "2 of 3 creators worth keeping. Every video should leave a viewer thinking: I could do that, and Muse would take care of me.",
     "MUSE", "#GoingOutWithMuse #MuseGirls #ForTheGirls", None,
     "Week 1 (Nov 19-22) Our first night with Muse: POV night vlog. Week 2 (Nov 23-29) Thanksgiving Eve Wed Nov 25: "
     "GRWM. Week 3 (Nov 30-Dec 6) Bring your bestie. Week 4 (Dec 7-13) Holiday party season: the honest review. "
     "Creator videos are tracked in the UGC creator tracker; this campaign holds the posts on the Muse account."),
    ("Why we made Thalia", "2026-11-22", "2026-12-13", "Planned",
     "Explain Thalia, Muse's assistant, in 7 reasons: a talking-head Reel and a 7-slide carousel each (14 posts). "
     "Reel first, carousel two days later.",
     None, None, THALIA_DOC,
     "Founder stories in the scripts are SAMPLES: replace each with a real story before filming. Open: who is on "
     "camera. Always \"Thalia, Muse's assistant\" (assistant or AI, never bot). No venue names, rates or free-table pitches."),
    ("Dayguard pilot", "2026-11-24", "2026-12-20", "Unconfirmed",
     "Brand collab pilot with Dayguard. Not confirmed yet: don't plan or post anything until the founder confirms it.",
     None, None, None, "Waiting on Dayguard's answers."),
]

# date, time, title, format, pillar, hook, caption, cta, content type, script
THALIA = [
    ("2026-11-22", "Nobody gets missed", "We used to leave girls on read. By accident.",
     "We missed messages before. Not anymore. Thalia answers every DM, and the team is one message away when you need a person.",
     "Nobody gets left on read anymore.", "If you ever gave up on our DMs, try again."),
    ("2026-11-25", "No surprises at the door", "The worst part of a night out is getting turned away.",
     "Dress code, what the guys need, who's hosting, ID. Thalia tells you all of it before you leave, so the door is the easy part. 21+.",
     "Walk in knowing everything.", "Ask her before you head out."),
    ("2026-11-29", "Always on", "2 AM and you want to know where we are?",
     "Thalia answers at 2 AM, on a Tuesday, whenever. And if you stop replying, she won't chase you.",
     "Always on, never pushy.", "Whatever time it is, the DMs are open."),
    ("2026-12-02", "Faster answers", "Why does Muse answer so fast now?",
     "Same Muse, faster answers. Thalia knows tonight's plan so you don't have to wait on us. And if she's not sure, a real person takes it from there.",
     "Swipe to meet the reason our replies got faster.", "DM us. Plans in minutes."),
    ("2026-12-06", "No new app", "We could've made you download an app. We didn't.",
     "No app, no sign-up. Thalia lives in our DMs, and you'll always know when a real person from the team takes over.",
     "The easiest way to make plans with Muse is the chat you already have.", "Open our DMs and say hi."),
    ("2026-12-09", "More time for guests", "Why our promoters aren't on their phones all night",
     "Thalia handles the planning so our team can be present with you on the night.",
     "More time for you, less time on our phones.", "Come out and meet the team."),
    ("2026-12-12", "Room to grow", "Why her name is Thalia",
     "Thalia is named after the Muse of festivity. She handles the planning so we can keep working on what matters: making going out better for women. What should we build next?",
     "This is just the start. Comment what you want next.", "Tell us what would make your nights out better."),
]
CAROUSEL_DATES = ["2026-11-24", "2026-11-27", "2026-12-01", "2026-12-04", "2026-12-08", "2026-12-11", "2026-12-13"]

OTHER_POSTS = [
    # date, time, title, format, pillar, campaign, hook, cta, content type, shots
    ("2026-11-23", "12:00", "Weekend recap (Monday series)", "Reel", "The Night", None, "", "Where are we going this weekend? DM us",
     "Night recap", "Best walk-in, table, fits and dance floor clips from Thu-Sat."),
    ("2026-11-26", "17:00", "Collab-post the best Thanksgiving Eve GRWM", "Collab Reel", "The Girls", "Going Out With Muse",
     "GRWM for Thanksgiving Eve", "DM @muse 'MUSE' for the list", "UGC", "Pick the strongest creator GRWM and post it as a Collab."),
    ("2026-11-30", "12:00", "Weekend recap (Monday series)", "Reel", "The Night", None, "", "Where are we going this weekend? DM us",
     "Night recap", "Thanksgiving Eve + weekend highlights."),
    ("2026-12-03", "19:00", "Bring your bestie: Reel stitching the creators' reviews", "Reel", "The Girls", "Going Out With Muse",
     "Taking my friend out for her first time", "DM @muse 'MUSE' for the list", "UGC", "Stitch the week 3 creator videos."),
    ("2026-12-07", "12:00", "Weekend recap (Monday series)", "Reel", "The Night", None, "", "Where are we going this weekend? DM us",
     "Night recap", ""),
    ("2026-12-13", "19:00", "Going Out With Muse best-of + name the first Ambassador", "Reel", "The Girls", "Going Out With Muse",
     "Rating my night out with Muse, out of 10", "DM @muse 'MUSE' for the list", "UGC",
     "Best moments from all 12 creator videos. Announce the first Muse Ambassador (picked by views and consistency, never looks)."),
]

# title, format, pillar, priority, details
IDEAS = [
    ("What is a promoter and why is it free?", "Carousel", "Muse 101", "High", "Explainer carousel. CTA: DM us FIRSTTIME."),
    ("Street interview series", "Reel", "The Girls", "High",
     "Weekly, same opening line and cover. In line, outside, at the table. Questions: craziest night out story, rate your fit, red flag on a night out, is a 5am night worth it."),
    ("GRWM for tonight", "Reel", "The Girls", "High", "Outfit and why it works for the dress code, ending at the door."),
    ("Caption over clip", "Reel", "It's So Real", "High", "One relatable line over night footage. Good use for library clips."),
    ("Photo spot carousel", "Carousel", "The Night", "High", "Best photo spots in the rooms we go to."),
    ("Dress code decoder (series)", "Reel", "Muse 101", "Medium", "One venue, 15 seconds."),
    ("Myth vs fact", "Carousel", "Muse 101", "Medium", "Myths about going out with a promoter."),
    ("Night-out timeline: why we say arrive by 11", "Carousel", "Muse 101", "Medium", ""),
    ("What's in my bag", "Reel", "The Girls", "Medium", ""),
    ("Muse Girl of the Week", "Carousel", "The Girls", "Medium", "Picked for her night, never her looks. Get her OK first."),
    ("POV skits / types of girls on a night out", "Reel", "It's So Real", "Medium", ""),
    ("Every girl at 2am", "Reel", "It's So Real", "Medium", ""),
    ("Expectation vs reality", "Reel", "It's So Real", "Low", ""),
    ("Outfit inspo by venue", "Carousel", "The Night", "Low", ""),
    ("Day in the life of a host", "Reel", "Behind Muse", "Medium", ""),
    ("Venue reveal", "Reel", "Behind Muse", "Low", "Check the venue's filming rules first."),
    ("Things my promoter did tonight that my ex never did", "Reel", "The Girls", "Medium", "Hook bank (UGC brief)."),
    ("I was scared to go out with a promoter. Here's what actually happened", "Reel", "The Girls", "Medium", "Hook bank (UGC brief)."),
]


def seed_social(con) -> None:
    if con.execute("SELECT 1 FROM plan LIMIT 1").fetchone() or con.execute("SELECT 1 FROM campaigns LIMIT 1").fetchone():
        return
    for name, start, end, status, goal, kw, tags, link, notes in CAMPAIGNS:
        con.execute("INSERT OR IGNORE INTO campaigns(name, start_date, end_date, status, goal, keyword, hashtags, brief_link,"
                    " notes) VALUES (?,?,?,?,?,?,?,?,?)", (name, start, end, status, goal, kw, tags, link, notes))
    rows = []
    for i, (day, reason, hook, reel_cap, car_cap, close) in enumerate(THALIA):
        rows.append((day, "19:00", f"Thalia #{i + 1}: {reason} (Reel)", "Reel", "Behind Muse", "Why we made Thalia",
                     hook, reel_cap, close, "Education",
                     "Talking-head Reel, 40-55s. Script in the Thalia series doc. Replace the sample founder story with a real one.", 1))
        rows.append((CAROUSEL_DATES[i], "12:00", f"Thalia #{i + 1}: {reason} (Carousel)", "Carousel", "Behind Muse",
                     "Why we made Thalia", hook, car_cap, close, "Education",
                     "7 slides, text in the Thalia series doc. Slide 4 = your real story in one line.", 1))
    for day, time, title, fmt, pillar, camp, hook, cta, ctype, shots in OTHER_POSTS:
        rows.append((day, time, title, fmt, pillar, camp, hook, None, cta, ctype, shots, 0))
    rows.sort(key=lambda r: (r[0], r[1]))
    for n, (day, time, title, fmt, pillar, camp, hook, cap, cta, ctype, shots, ok) in enumerate(rows, 1):
        con.execute("INSERT INTO plan(id, planned_date, planned_time, title, format, pillar, campaign, status, needs_approval,"
                    " hook, caption, cta, content_type, shot_list, brief_link) VALUES (?,?,?,?,?,?,?, 'Planned', ?,?,?,?,?,?,?)",
                    (f"P-{n:05d}", day, time, title, fmt, pillar, camp, ok, hook or None, cap, cta, ctype, shots or None,
                     THALIA_DOC if camp == "Why we made Thalia" else None))
    for n, (title, fmt, pillar, prio, details) in enumerate(IDEAS, 1):
        con.execute("INSERT INTO ideas(id, title, format, pillar, priority, status, details) VALUES (?,?,?,?,?, 'New', ?)",
                    (f"I-{n:05d}", title, fmt, pillar, prio, details or None))
