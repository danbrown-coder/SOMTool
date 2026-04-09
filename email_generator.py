"""AI email generation via OpenAI with template fallback."""
from __future__ import annotations

import json
import os
import re
from typing import Any, NamedTuple

from dotenv import load_dotenv

load_dotenv()


class GeneratedEmail(NamedTuple):
    subject: str
    body: str


_HUMAN_SYSTEM_BASE = (
    "You are writing as a real employee at the Cal Lutheran School of Management. "
    "Write like a human — casual-professional tone, varied sentence structure. "
    "NEVER use phrases like 'I hope this email finds you well', "
    "'I am reaching out to...', 'I wanted to take a moment to...', 'Thank you for your time and consideration', "
    "'Please do not hesitate to contact us', or 'I am writing to inform you'. These sound robotic. "
    "CRITICAL: You will be given background info about the recipient (their company, title, LinkedIn, etc). "
    "USE this info to make the email feel personal — reference their company by name, mention their "
    "specific expertise, tie it to the event. If they have a LinkedIn, you can reference something "
    "about their professional profile. Do NOT just say 'given your background' — be SPECIFIC. "
    "Each email must feel like it was written individually for that one person. "
    "Keep it short (3-6 sentences for the body). Be direct and warm. "
    "Sign off with just a first name and title, like:\n"
    "— Alex\nEvents Coordinator, School of Management\n\n"
    "Always respond with exactly: first line 'SUBJECT: ...' then a blank line then the email body. "
    "No markdown formatting."
)


def _get_system_prompt() -> str:
    """Build the full system prompt by combining the base with admin AI config."""
    try:
        import ai_config
        cfg = ai_config.load_config()
    except Exception:
        return _HUMAN_SYSTEM_BASE

    extra_parts: list[str] = []
    personality = cfg.get("personality", "")
    if personality:
        extra_parts.append(f"ADMIN PERSONALITY INSTRUCTIONS: {personality}")
    email_rules = cfg.get("email_rules", "")
    if email_rules:
        extra_parts.append(f"ADMIN EMAIL RULES: {email_rules}")

    if not extra_parts:
        return _HUMAN_SYSTEM_BASE
    return _HUMAN_SYSTEM_BASE + "\n\n" + "\n".join(extra_parts)


def _build_recipient_context(
    recipient_name: str,
    company: str = "",
    title: str = "",
    linkedin_url: str = "",
    tags: list[str] | None = None,
    notes: str = "",
) -> str:
    """Build a context block about the recipient for the AI to personalize from."""
    parts = [f"Name: {recipient_name}"]
    if company:
        parts.append(f"Company/Organization: {company}")
    if title:
        parts.append(f"Title/Position: {title}")
    if linkedin_url:
        parts.append(f"LinkedIn: {linkedin_url}")
    if tags:
        parts.append(f"Tags/Affiliations: {', '.join(tags)}")
    if notes:
        parts.append(f"Background notes: {notes[:300]}")
    return "\n".join(parts)

_ROLE_TONE: dict[str, str] = {
    "speaker": (
        "You're writing to someone you'd like as a speaker. Reference their expertise or background, "
        "mention the audience they'd be speaking to, and ask about their availability and any topic "
        "preferences. Be respectful of their time — they're doing you a favor."
    ),
    "panelist": (
        "You're inviting someone to join a panel discussion. Mention the panel topic and what perspective "
        "you think they'd bring. Keep it conversational — panels are collaborative, not formal."
    ),
    "moderator": (
        "You're asking someone to moderate a session. Reference their facilitation skills or leadership "
        "background. Mention the panel or session they'd be guiding and the caliber of panelists."
    ),
    "judge": (
        "You're inviting them to judge a competition or pitch event. Emphasize the format, what judging "
        "looks like, and why their industry experience makes them a great fit. Make it sound exciting."
    ),
    "sponsor": (
        "You're reaching out about sponsorship. Focus on visibility, audience demographics, and the value "
        "proposition. Be specific about what sponsorship includes — but keep the tone partnership-oriented, "
        "not salesy."
    ),
    "faculty": (
        "You're writing to a faculty member or academic colleague. Use a collegial tone, reference the "
        "academic angle of the event, and mention student involvement or learning outcomes."
    ),
    "attendee": (
        "You're inviting someone to attend. Keep it lighter and shorter than other roles — emphasize "
        "networking value, key takeaways, or why this event is worth their evening. Don't oversell."
    ),
    "organizer": (
        "You're writing to a co-organizer or planning partner. Be practical and direct — mention logistics, "
        "timelines, or next steps. Treat them as an equal collaborator."
    ),
    "staff": (
        "You're writing to university staff or administration. Be professional but warm, reference the "
        "institutional value of the event and how their support matters."
    ),
}

_FOLLOWUP_ROLE_TONE: dict[str, str] = {
    "speaker": (
        "They were invited to SPEAK at this event. Remind them specifically that you asked them to "
        "give a talk/presentation. Mention you're still finalizing the speaker lineup and their "
        "session would be a highlight. Ask if they need more info about the format or audience."
    ),
    "panelist": (
        "They were invited as a PANELIST. Remind them of the panel topic and that you wanted their "
        "perspective specifically. Mention you're confirming the panel lineup and their voice matters."
    ),
    "moderator": (
        "They were asked to MODERATE a session. Remind them what session they'd be guiding and that "
        "you chose them because of their facilitation skills. Keep it brief — moderators are busy."
    ),
    "judge": (
        "They were invited to JUDGE a competition. Remind them it's a judging role, mention the "
        "format briefly (pitch competition, mock draft, etc.), and that their industry eye would "
        "make a real difference for the student teams."
    ),
    "sponsor": (
        "You reached out about SPONSORSHIP. Don't be pushy — acknowledge they're probably evaluating "
        "options. Mention one concrete benefit (audience size, visibility) and offer to hop on a quick call."
    ),
    "faculty": (
        "They were invited in a FACULTY capacity. Reference the academic connection and how their "
        "students could benefit. Keep it collegial."
    ),
    "attendee": (
        "They were invited to ATTEND. Keep it super short and light — just a friendly nudge. "
        "Mention one specific reason this event is worth their time (a keynote speaker, networking, etc.)."
    ),
    "organizer": (
        "They're a co-ORGANIZER. Be direct — you need their input on something specific. "
        "Reference a logistics item or decision that's pending their response."
    ),
    "staff": (
        "They're involved as STAFF support. Be practical — mention what you need from them and "
        "when the deadline is."
    ),
}


def _role_tone_for(contact_role: str) -> str:
    return _ROLE_TONE.get(contact_role, _ROLE_TONE["attendee"])


def _client():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=key)
    except Exception:
        return None


# ── Fallbacks (human-sounding, role-aware) ───────────────────


def _fallback_initial(
    event_name: str,
    event_date: str,
    event_description: str,
    audience_type: str,
    recipient_name: str,
    contact_role: str = "attendee",
    company: str = "",
) -> GeneratedEmail:
    role_label = contact_role.replace("_", " ")
    co = f" at {company}" if company else ""
    if contact_role == "speaker":
        subject = f"Would you speak at {event_name}?"
        body = (
            f"Hi {recipient_name},\n\n"
            f"We're putting together {event_name} on {event_date} and your name kept coming up "
            f"as someone who'd be a great fit to speak{co}. The audience is {audience_type} — "
            f"I think they'd really benefit from your perspective.\n\n"
            f"Would you be open to a quick chat about it?\n\n"
            "— Alex\nEvents Coordinator, School of Management"
        )
    elif contact_role in ("panelist", "moderator"):
        subject = f"{event_name} — join us as a {role_label}?"
        body = (
            f"Hi {recipient_name},\n\n"
            f"We're hosting {event_name} on {event_date} and given your work{co}, "
            f"I think you'd be a fantastic {role_label}. {event_description[:120]}\n\n"
            f"Let me know if this sounds interesting and I'll send over more details.\n\n"
            "— Alex\nEvents Coordinator, School of Management"
        )
    elif contact_role == "judge":
        subject = f"Judge our competition? — {event_name}"
        body = (
            f"Hi {recipient_name},\n\n"
            f"We're running {event_name} on {event_date} and we need sharp judges "
            f"with real-world experience. Given your background{co}, I immediately thought of you.\n\n"
            f"It's a half-day commitment and honestly a lot of fun. Interested?\n\n"
            "— Alex\nEvents Coordinator, School of Management"
        )
    elif contact_role == "sponsor":
        subject = f"Sponsorship opportunity — {event_name}"
        body = (
            f"Hi {recipient_name},\n\n"
            f"{event_name} is coming up on {event_date} and we think there's a great "
            f"alignment between {company or 'your organization'} and our audience ({audience_type}). "
            f"I'd love to explore a partnership.\n\n"
            f"Happy to jump on a call whenever works for you.\n\n"
            "— Alex\nEvents Coordinator, School of Management"
        )
    else:
        subject = f"You're invited — {event_name} ({event_date})"
        body = (
            f"Hi {recipient_name},\n\n"
            f"Wanted to let you know about {event_name} happening on {event_date}. "
            f"{event_description[:150]}\n\n"
            f"I think you'd get a lot out of it — would love to see you there.\n\n"
            "— Alex\nEvents Coordinator, School of Management"
        )
    return GeneratedEmail(subject=subject, body=body)


def _fallback_followup(
    event_name: str,
    event_date: str,
    recipient_name: str,
    contact_role: str = "attendee",
    company: str = "",
) -> GeneratedEmail:
    role_label = contact_role.replace("_", " ")
    co = f" at {company}" if company else ""

    if contact_role == "speaker":
        subject = f"Still hoping you'll speak — {event_name}"
        body = (
            f"Hi {recipient_name},\n\n"
            f"Circling back on our invite to speak at {event_name} ({event_date}). "
            f"We're finalizing the speaker lineup and your talk would genuinely be "
            f"a highlight{co}.\n\n"
            f"Totally understand if the timing doesn't work — just let me know either way "
            f"so I can plan accordingly.\n\n"
            "— Alex\nEvents Coordinator, School of Management"
        )
    elif contact_role == "panelist":
        subject = f"Panel spot — {event_name}"
        body = (
            f"Hi {recipient_name},\n\n"
            f"Following up on the panelist invite for {event_name} ({event_date}). "
            f"We're putting together a strong panel and your perspective{co} "
            f"would add a lot.\n\n"
            f"Any chance you can join? Even a quick yes/no helps me finalize things.\n\n"
            "— Alex\nEvents Coordinator, School of Management"
        )
    elif contact_role == "judge":
        subject = f"Judging at {event_name} — quick follow-up"
        body = (
            f"Hi {recipient_name},\n\n"
            f"Just bumping the judge invitation for {event_name} ({event_date}). "
            f"We need industry professionals{co} to evaluate the student teams and "
            f"your experience would really elevate the competition.\n\n"
            f"It's a half-day commitment — let me know if you're in!\n\n"
            "— Alex\nEvents Coordinator, School of Management"
        )
    elif contact_role == "sponsor":
        subject = f"Sponsorship follow-up — {event_name}"
        body = (
            f"Hi {recipient_name},\n\n"
            f"Wanted to follow up on the sponsorship opportunity for {event_name} ({event_date}). "
            f"I think there's real alignment between {company or 'your organization'} and our "
            f"audience.\n\n"
            f"Happy to jump on a 10-minute call to walk through the details whenever works.\n\n"
            "— Alex\nEvents Coordinator, School of Management"
        )
    elif contact_role == "moderator":
        subject = f"Moderator role — {event_name}"
        body = (
            f"Hi {recipient_name},\n\n"
            f"Following up on the moderator invite for {event_name} ({event_date}). "
            f"We've got a great panel coming together and need someone sharp{co} "
            f"to keep the conversation flowing.\n\n"
            f"Let me know if you're available — happy to share more details.\n\n"
            "— Alex\nEvents Coordinator, School of Management"
        )
    elif contact_role == "faculty":
        subject = f"Quick follow-up — {event_name}"
        body = (
            f"Hi {recipient_name},\n\n"
            f"Just circling back on {event_name} ({event_date}). Your involvement "
            f"would be great for the students and we'd love to have you represent "
            f"the academic side.\n\n"
            f"Any thoughts?\n\n"
            "— Alex\nEvents Coordinator, School of Management"
        )
    else:
        subject = f"Don't miss {event_name}"
        body = (
            f"Hi {recipient_name},\n\n"
            f"Quick nudge — {event_name} is on {event_date} and I think "
            f"you'd get a lot out of it. Great networking and some really "
            f"strong speakers lined up.\n\n"
            f"Hope to see you there!\n\n"
            "— Alex\nEvents Coordinator, School of Management"
        )
    return GeneratedEmail(subject=subject, body=body)


# ── AI-powered generators ───────────────────────────────────


def generate_initial_email(
    event_name: str,
    event_date: str,
    event_description: str,
    audience_type: str,
    recipient_name: str,
    contact_role: str = "attendee",
    company: str = "",
    title: str = "",
    linkedin_url: str = "",
    tags: list[str] | None = None,
    notes: str = "",
) -> GeneratedEmail:
    client = _client()
    fallback = _fallback_initial(
        event_name, event_date, event_description, audience_type, recipient_name,
        contact_role, company,
    )
    if not client:
        return fallback
    role_guidance = _role_tone_for(contact_role)
    recipient_ctx = _build_recipient_context(recipient_name, company, title, linkedin_url, tags, notes)
    user_prompt = (
        f"Event: {event_name}\n"
        f"Date: {event_date}\n"
        f"Description: {event_description}\n"
        f"Audience: {audience_type}\n"
        f"Their role at this event: {contact_role.replace('_', ' ')}\n\n"
        f"--- RECIPIENT INFO (use this to personalize!) ---\n{recipient_ctx}\n---\n\n"
        f"Role-specific guidance: {role_guidance}\n\n"
        "Write a personalized outreach email. Reference something specific about them."
    )
    try:
        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": _get_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=600,
        )
        text = (resp.choices[0].message.content or "").strip()
        return _parse_subject_body(text, fallback)
    except Exception:
        return fallback


def generate_followup_email(
    event_name: str,
    event_date: str,
    recipient_name: str,
    contact_role: str = "attendee",
    company: str = "",
    title: str = "",
    linkedin_url: str = "",
    tags: list[str] | None = None,
    notes: str = "",
) -> GeneratedEmail:
    client = _client()
    fallback = _fallback_followup(event_name, event_date, recipient_name, contact_role, company)
    if not client:
        return fallback
    followup_guidance = _FOLLOWUP_ROLE_TONE.get(contact_role, _FOLLOWUP_ROLE_TONE["attendee"])
    recipient_ctx = _build_recipient_context(recipient_name, company, title, linkedin_url, tags, notes)
    role_label = contact_role.replace("_", " ")
    user_prompt = (
        f"Event: {event_name}\n"
        f"Date: {event_date}\n"
        f"Their assigned role at this event: {role_label}\n\n"
        f"--- RECIPIENT INFO (use this to personalize!) ---\n{recipient_ctx}\n---\n\n"
        f"Follow-up context: {followup_guidance}\n\n"
        f"This person was previously contacted to be a {role_label} at {event_name} but "
        f"hasn't responded yet. Write a follow-up that:\n"
        f"1. Reminds them SPECIFICALLY what they were asked to do (be a {role_label})\n"
        f"2. References their background/company to show you know who they are\n"
        f"3. Is brief, casual, and understanding — not a generic 'just checking in'\n"
        f"4. Gives them an easy way to respond (yes/no, quick call, etc.)"
    )
    try:
        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": _get_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=400,
        )
        text = (resp.choices[0].message.content or "").strip()
        return _parse_subject_body(text, fallback)
    except Exception:
        return fallback


def generate_event_update_email(
    event_name: str,
    event_date: str,
    recipient_name: str,
    update_description: str,
    contact_role: str = "attendee",
    company: str = "",
    title: str = "",
    notes: str = "",
) -> GeneratedEmail:
    """Generate an email notifying a contact about an event update."""
    client = _client()
    fallback = GeneratedEmail(
        subject=f"Quick update — {event_name}",
        body=(
            f"Hi {recipient_name},\n\n"
            f"Heads up — there's been an update to {event_name} ({event_date}):\n\n"
            f"{update_description}\n\n"
            f"Let me know if you have any questions.\n\n"
            "— Alex\nEvents Coordinator, School of Management"
        ),
    )
    if not client:
        return fallback
    role_guidance = _role_tone_for(contact_role)
    recipient_ctx = _build_recipient_context(recipient_name, company, title, notes=notes)
    user_prompt = (
        f"Event: {event_name}\n"
        f"Date: {event_date}\n"
        f"Their role: {contact_role.replace('_', ' ')}\n"
        f"Update: {update_description}\n\n"
        f"--- RECIPIENT INFO ---\n{recipient_ctx}\n---\n\n"
        f"Role-specific guidance: {role_guidance}\n\n"
        "Write a short, direct email about this update. Don't repeat the whole event pitch — "
        "just share the news and be helpful."
    )
    try:
        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": _get_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=400,
        )
        text = (resp.choices[0].message.content or "").strip()
        return _parse_subject_body(text, fallback)
    except Exception:
        return fallback


def generate_referral_request_email(
    event_name: str,
    event_date: str,
    recipient_name: str,
    sender_role: str = "attendee",
    target_role: str = "attendee",
    company: str = "",
    title: str = "",
    linkedin_url: str = "",
    tags: list[str] | None = None,
    notes: str = "",
) -> GeneratedEmail:
    """Ask an existing contact to refer someone for a specific role."""
    client = _client()
    target_label = target_role.replace("_", " ")
    sender_label = sender_role.replace("_", " ")
    fallback = GeneratedEmail(
        subject=f"Know a great {target_label}? — {event_name}",
        body=(
            f"Hi {recipient_name},\n\n"
            f"Thanks again for being part of {event_name} ({event_date}). "
            f"We're looking for a strong {target_label} and I figured you might know "
            f"someone perfect given your own experience"
            f"{' at ' + company if company else ''}.\n\n"
            f"If anyone comes to mind, I'd love a name or intro — "
            f"even a quick \"try reaching out to so-and-so\" would be huge.\n\n"
            "— Alex\nEvents Coordinator, School of Management"
        ),
    )
    if not client:
        return fallback

    recipient_ctx = _build_recipient_context(recipient_name, company, title, linkedin_url, tags, notes)
    sender_context = {
        "speaker": f"They are currently a confirmed speaker. Leverage the fact that speakers know other great speakers in their field.",
        "panelist": f"They are a panelist. They likely know peers in their industry who could fill the {target_label} role.",
        "judge": f"They are a judge for the event. Judges often know accomplished professionals who'd be great as a {target_label}.",
        "moderator": f"They are moderating a session. Moderators have wide networks — tap into that.",
        "sponsor": f"They are a sponsor. They may know executives or community figures who'd be a good {target_label}.",
        "faculty": f"They are faculty. They can recommend colleagues, alumni, or industry contacts.",
        "attendee": f"They are an attendee. Keep it simple — ask casually if they know anyone who'd be a good {target_label}.",
    }

    user_prompt = (
        f"Event: {event_name}\n"
        f"Date: {event_date}\n"
        f"Recipient's current role in this event: {sender_label}\n"
        f"Role you're trying to fill: {target_label}\n\n"
        f"--- RECIPIENT INFO (personalize using this!) ---\n{recipient_ctx}\n---\n\n"
        f"Context: {sender_context.get(sender_role, sender_context['attendee'])}\n\n"
        f"Write a personal, natural email asking them to recommend someone for the {target_label} role. "
        f"Reference their company/background and their own involvement to make the ask feel organic."
    )
    try:
        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": _get_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.85,
            max_tokens=500,
        )
        text = (resp.choices[0].message.content or "").strip()
        return _parse_subject_body(text, fallback)
    except Exception:
        return fallback


# ── Recommendation engine ────────────────────────────────────


def recommend_people_for_event(
    event_name: str,
    event_date: str,
    description: str,
    audience_type: str,
    people_summaries: list[dict[str, Any]],
    target_role: str = "",
) -> list[dict[str, Any]]:
    """
    Return list of {person_id, reason} sorted by relevance.
    people_summaries: {id, name, email, company, role, tags}
    target_role: e.g. "speaker", "panelist", "judge" — filters recommendations.
    """
    client = _client()
    if not client or not people_summaries:
        return _fallback_recommend_tag_match(audience_type, people_summaries, target_role)

    lines = []
    for p in people_summaries:
        lines.append(
            f"- id={p['id']}|{p['name']}|{p.get('email','')}|"
            f"{p.get('company','')}|{p.get('role','')}|tags:{','.join(p.get('tags', []))}"
        )
    blob = "\n".join(lines[:200])

    role_instruction = ""
    if target_role:
        role_label = target_role.replace("_", " ").title()
        role_instruction = (
            f"\nYou are looking specifically for someone to fill the role of **{role_label}** "
            f"at this event. Only pick people who would be a strong fit as a {role_label}. "
            f"Explain in the reason why they'd be good in that specific role."
        )

    user_prompt = (
        f"Event: {event_name}\nDate: {event_date}\nAudience: {audience_type}\n"
        f"Description: {description}{role_instruction}\n\nPeople:\n{blob}\n\n"
        "Pick up to 12 most relevant people. Respond with ONLY valid JSON array: "
        '[{"person_id":"<uuid>","reason":"one sentence"}]'
    )
    try:
        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "system",
                    "content": "You output only JSON arrays. No markdown.",
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=1200,
        )
        text = (resp.choices[0].message.content or "").strip()
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        data = json.loads(text)
        if not isinstance(data, list):
            return _fallback_recommend_tag_match(audience_type, people_summaries, target_role)
        out = []
        for item in data:
            if isinstance(item, dict) and item.get("person_id"):
                out.append(
                    {
                        "person_id": item["person_id"],
                        "reason": str(item.get("reason", "Good fit")),
                    }
                )
        return out[:12]
    except Exception:
        return _fallback_recommend_tag_match(audience_type, people_summaries, target_role)


def _fallback_recommend_tag_match(
    audience_type: str,
    people_summaries: list[dict[str, Any]],
    target_role: str = "",
) -> list[dict[str, Any]]:
    ROLE_TAG_HINTS: dict[str, list[str]] = {
        "speaker": ["speaker", "ess-speaker", "techtalk-speaker", "cerf-speaker",
                     "mppa-speaker", "fireside-chat-speaker"],
        "panelist": ["speaker", "pathways-speaker", "deij-speaker", "exec-talent-forum",
                      "hr-leader", "industry"],
        "judge": ["sports-management-judge", "sdcie-council", "entrepreneur-in-residence",
                   "c-suite", "industry"],
        "moderator": ["faculty", "leadership", "advisory-council"],
        "sponsor": ["venture-capital", "c-suite", "finance"],
        "faculty": ["faculty"],
        "attendee": ["alumni", "industry", "entrepreneur"],
    }
    if target_role and target_role in ROLE_TAG_HINTS:
        tag_hints = ROLE_TAG_HINTS[target_role]
    else:
        aud = audience_type.lower()
        tag_hints = []
        if "alumni" in aud:
            tag_hints.append("alumni")
        if "student" in aud:
            tag_hints.append("student")
        if "faculty" in aud:
            tag_hints.append("faculty")
        if "industry" in aud or "partner" in aud:
            tag_hints.append("industry")
        if not tag_hints:
            tag_hints = ["speaker", "alumni", "student"]

    label = target_role.replace("_", " ").title() if target_role else audience_type
    out: list[dict[str, Any]] = []
    for p in people_summaries:
        tags = [t.lower() for t in p.get("tags", [])]
        if any(h in tags for h in tag_hints):
            out.append(
                {
                    "person_id": p["id"],
                    "reason": f"Tag match for {label} role.",
                }
            )
    if not out:
        for p in people_summaries[:8]:
            out.append(
                {
                    "person_id": p["id"],
                    "reason": "General pool match (enable OpenAI for smarter picks).",
                }
            )
    return out[:12]


# ── Discovery ────────────────────────────────────────────────


def discover_prospects_from_text(
    event_name: str,
    search_results_text: str,
    target_role: str = "",
) -> list[dict[str, str]]:
    """Parse search snippets into prospect rows (name, org, url, note)."""
    client = _client()
    if not client:
        return _fallback_discover_lines(search_results_text)
    role_hint = ""
    if target_role:
        role_label = target_role.replace("_", " ").title()
        role_hint = (
            f" Focus on people who would be a strong **{role_label}** for this event."
            f" In the note field, explain why they'd be a good {role_label}."
        )
    user_prompt = (
        f"Event theme: {event_name}\n\nSearch results:\n{search_results_text[:8000]}\n\n"
        f"Extract up to 8 plausible professional prospects.{role_hint} JSON only: "
        '[{"name":"...","organization":"...","url":"...","note":"..."}] '
        "Use empty string if unknown."
    )
    try:
        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "Output only JSON arrays. No markdown."},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1000,
        )
        text = (resp.choices[0].message.content or "").strip()
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        data = json.loads(text)
        if not isinstance(data, list):
            return _fallback_discover_lines(search_results_text)
        out = []
        for row in data:
            if isinstance(row, dict) and row.get("name"):
                out.append(
                    {
                        "name": str(row.get("name", "")),
                        "organization": str(row.get("organization", "")),
                        "url": str(row.get("url", "")),
                        "note": str(row.get("note", "")),
                    }
                )
        return out[:8]
    except Exception:
        return _fallback_discover_lines(search_results_text)


def _fallback_discover_lines(text: str) -> list[dict[str, str]]:
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 20][:8]
    return [
        {
            "name": f"Prospect {i+1}",
            "organization": "",
            "url": "",
            "note": ln[:200],
        }
        for i, ln in enumerate(lines)
    ]


# ── Helpers ──────────────────────────────────────────────────


def _parse_subject_body(text: str, fallback: GeneratedEmail) -> GeneratedEmail:
    lines = text.split("\n")
    if not lines:
        return fallback
    first = lines[0].strip()
    if first.upper().startswith("SUBJECT:"):
        subject = first.split(":", 1)[1].strip()
        body_lines = []
        i = 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        body_lines = lines[i:]
        body = "\n".join(body_lines).strip() or fallback.body
        if not subject:
            subject = fallback.subject
        return GeneratedEmail(subject=subject, body=body)
    return GeneratedEmail(subject=fallback.subject, body=text)
