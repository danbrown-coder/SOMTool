"""Step-by-step "how to get these keys" copy for every Hub provider.

Rendered inside the Set-up-keys drawer on each Hub tile. Each entry is a
pure-data dict so non-technical admins can click-through without leaving
the app. Keep steps imperative, short, and in the order a human actually
performs them.

Schema per provider::

    "provider_slug": {
      "docs_url":      "https://...",
      "redirect_hint": "One-line sentence placed next to the copyable redirect URI.",
      "steps":         ["Step 1 ...", "Step 2 ...", ...],
      "field_hints":   { "ENV_VAR_NAME": "Where to find this specific value." },
    }
"""
from __future__ import annotations


_REDIRECT_NOTE = (
    "Paste the redirect URI shown below into your app's allowed redirect list "
    "(labels vary: \"Redirect URI\", \"Callback URL\", or \"Authorized redirect\")."
)


DOCS: dict[str, dict] = {
    # ── Default layer ──────────────────────────────────
    "google": {
        "docs_url": "https://console.cloud.google.com/apis/credentials",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to console.cloud.google.com and create (or select) a project.",
            "APIs & Services -> Library: enable Calendar, Gmail, Drive, Sheets, Forms, People, and Identity APIs (Google People, Forms, Sheets).",
            "APIs & Services -> OAuth consent screen: set Internal (if you're a Workspace) or External + Testing, add your email as a test user.",
            "APIs & Services -> Credentials -> Create Credentials -> OAuth client ID -> Web application.",
            "Paste the Redirect URI below into \"Authorized redirect URIs\" and save.",
            "Copy the Client ID and Client Secret into the fields on the right.",
            "(Optional) For live two-way Calendar sync, set GCAL_WEBHOOK_URL to a public HTTPS URL pointing at /gcal/webhook (use a tunnel like ngrok/Cloudflare in dev). Leave blank and SOMTool still pushes to Google, but changes Google-side won't flow back.",
        ],
        "field_hints": {
            "GOOGLE_CLIENT_ID": "Shown on the OAuth client screen after you create it.",
            "GOOGLE_CLIENT_SECRET": "Shown once when the OAuth client is created; regenerate if lost.",
            "GOOGLE_REDIRECT_URI": "Use the suggested value exactly; it must match what's in the Google console.",
            "GCAL_WEBHOOK_URL": "Optional. Public HTTPS endpoint for Google Calendar push notifications, e.g. https://your-host/gcal/webhook. Leave empty to disable Google -> SOMTool sync (outbound sync still works).",
        },
    },

    # ── Campus ─────────────────────────────────────────
    "canvas": {
        "docs_url": "https://canvas.instructure.com/doc/api/file.oauth.html",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Ask your Canvas admin (or Site Admin) to open Admin -> Developer Keys.",
            "Click \"+ Developer Key\" -> \"API Key\".",
            "Set the Redirect URIs to the value below, leave scopes open, and Save.",
            "Flip the key's state to ON. Copy the \"ID\" (Client ID) and \"Key\" (Client Secret).",
            "Set CANVAS_BASE_URL to your institution's Canvas URL (e.g. https://canvas.school.edu).",
        ],
        "field_hints": {
            "CANVAS_BASE_URL": "Your institution's Canvas domain, no trailing slash.",
        },
    },
    "twentyfivelive": {
        "docs_url": "https://knowledge25.collegenet.com/display/WEBSERV25/WebServices+API",
        "redirect_hint": "25Live uses HTTP Basic auth -- no redirect URI required.",
        "steps": [
            "Have your 25Live admin create a service account with read + space-hold permissions.",
            "Confirm the Web Services API is enabled on your 25Live instance.",
            "Paste the service account username and password below.",
            "Set 25LIVE_BASE_URL to your institution's API host (usually https://webservices.collegenet.com/r25ws/wrd/<school>/run).",
        ],
        "field_hints": {
            "TWENTYFIVELIVE_USERNAME": "25Live service account username.",
            "TWENTYFIVELIVE_PASSWORD": "Service account password.",
        },
    },
    "handshake": {
        "docs_url": "https://joinhandshake.com/partners/",
        "redirect_hint": "Handshake uses a partner API token issued to your school.",
        "steps": [
            "Contact your Handshake Customer Success manager and request API access for \"SOMTool / Event operations\".",
            "They will issue an institution ID + bearer token.",
            "Paste the token below and set HANDSHAKE_INSTITUTION_ID.",
        ],
    },
    "sis": {
        "docs_url": "",
        "redirect_hint": "Custom SIS endpoint. The API key below is used as a bearer token.",
        "steps": [
            "Ask your SIS vendor (Workday / Banner / PeopleSoft / Jenzabar) for a read-only REST token.",
            "Set CAMPUS_SIS_BASE_URL to the full REST root (including /api/v1 if required).",
            "Set CAMPUS_SIS_TENANT when your vendor partitions data by tenant (Workday, Ellucian).",
            "Paste the API token in the field on the right.",
        ],
    },
    "qualtrics": {
        "docs_url": "https://api.qualtrics.com/ZG9jOjg3NzY3Mg-quick-start",
        "redirect_hint": "Qualtrics uses an API token, not OAuth, so no redirect is needed.",
        "steps": [
            "Sign in to Qualtrics and open Account Settings -> Qualtrics IDs.",
            "Click \"Generate Token\" under the API section. Copy the token.",
            "Your data center is in the URL you use to sign in (e.g. yul1, fra1). Paste it below.",
        ],
        "field_hints": {
            "QUALTRICS_DATA_CENTER": "3-4 char ID from your Qualtrics URL (e.g. yul1).",
        },
    },
    "engage": {
        "docs_url": "https://engagesupport.campuslabs.com/hc/en-us/articles/204033724-Engage-API",
        "redirect_hint": "Engage / Campus Groups use a tenant-specific API key.",
        "steps": [
            "Choose your platform: campuslabs_engage, campusgroups, presence, or cglink.",
            "Log in to your platform admin and request API access for \"SOMTool\".",
            "Paste the bearer token below and set CAMPUS_ORG_PLATFORM.",
        ],
        "field_hints": {
            "CAMPUS_ORG_PLATFORM": "One of: campuslabs_engage, campusgroups, presence, cglink.",
        },
    },

    # ── Registration & ticketing ───────────────────────
    "eventbrite": {
        "docs_url": "https://www.eventbrite.com/platform/api-keys",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Sign in at eventbrite.com and open Account Settings -> Developer links -> API Keys.",
            "Click \"Create API Key\" and name it \"SOMTool\".",
            "Click \"OAuth\" tab on that app and paste the Redirect URI below.",
            "Copy the API Key (Client ID), Client Secret, and save them on the right.",
            "Optional: generate a webhook verification token under \"Webhooks\" and paste it into EVENTBRITE_WEBHOOK_TOKEN.",
        ],
    },
    "luma": {
        "docs_url": "https://lu.ma/docs/api",
        "redirect_hint": "Luma uses an API key on a team account.",
        "steps": [
            "Sign in at lu.ma and open Calendar Settings -> Integrations -> API.",
            "Click \"Create API Key\" and label it SOMTool.",
            "Copy the key into the field on the right.",
        ],
    },
    "wallet": {
        "docs_url": "https://developer.apple.com/documentation/walletpasses",
        "redirect_hint": "Wallet passes are signed with your Apple / Google credentials, not OAuth.",
        "steps": [
            "Apple: join Apple Developer and create a Pass Type ID cert in developer.apple.com -> Certificates.",
            "Export the signing certificate as .p12 and set APPLE_WALLET_CERT_P12_PATH to its absolute path.",
            "Paste the .p12 password into APPLE_WALLET_CERT_PASSWORD.",
            "Set APPLE_WALLET_TEAM_ID (found in the top-right of developer.apple.com).",
            "Google: follow pay.google.com/business/console to create an Issuer ID and service account JSON.",
        ],
    },

    # ── CRM & Marketing ────────────────────────────────
    "hubspot": {
        "docs_url": "https://developers.hubspot.com/docs/api/overview",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to app.hubspot.com/developer -> Apps -> Create app.",
            "Open the app -> Auth: paste the Redirect URI below.",
            "Select scopes: crm.objects.contacts.read, crm.objects.contacts.write, crm.schemas.contacts.read.",
            "Copy Client ID + Client Secret from the Auth tab.",
            "Optional: enable Webhooks and paste the app secret into HUBSPOT_WEBHOOK_SECRET.",
        ],
    },
    "salesforce": {
        "docs_url": "https://help.salesforce.com/s/articleView?id=sf.connected_app_create.htm",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "In Salesforce Setup -> App Manager -> New Connected App.",
            "Enable OAuth; paste the Redirect URI (Callback URL) below.",
            "Select scopes: Access the identity URL service, Manage user data via APIs, Perform requests at any time (refresh_token).",
            "Save. Wait ~5 minutes for propagation. Open the app -> Manage Consumer Details to copy Client ID and Secret.",
            "Set SALESFORCE_LOGIN_URL to https://login.salesforce.com (production) or https://test.salesforce.com (sandbox).",
        ],
    },
    "mailchimp": {
        "docs_url": "https://mailchimp.com/developer/marketing/guides/access-user-data-oauth-2/",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to admin.mailchimp.com -> Account & billing -> Extras -> Registered apps.",
            "Click \"Register An App\" and set the Redirect URI to the value below.",
            "Copy the Client ID and Client Secret on the app detail page.",
            "Set MAILCHIMP_AUDIENCE_ID to the list you want SOMTool to sync into (Audience -> Settings -> Audience name and defaults).",
        ],
    },
    "linkedin_sales": {
        "docs_url": "https://www.linkedin.com/developers/apps",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to linkedin.com/developers/apps -> Create app (link it to a Company Page).",
            "Under \"Products\", request \"Sign In with LinkedIn using OpenID Connect\" and, if available, \"Sales Navigator API\".",
            "Under Auth, paste the Redirect URI below.",
            "Copy the Client ID + Client Secret.",
        ],
    },

    # ── Ops & Productivity ─────────────────────────────
    "notion": {
        "docs_url": "https://developers.notion.com/docs/authorization",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to notion.so/my-integrations -> New integration.",
            "Choose \"Public integration\" so multiple users can connect.",
            "Paste the Redirect URI below under \"OAuth Domain & URIs\".",
            "Copy the OAuth Client ID + Client Secret from the \"Secrets\" section.",
        ],
    },
    "airtable": {
        "docs_url": "https://airtable.com/developers/web/api/oauth-reference",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to airtable.com/create/oauth -> Register new OAuth integration.",
            "Paste the Redirect URI below.",
            "Scopes: data.records:read, data.records:write, schema.bases:read.",
            "Save. Copy the Client ID and (click \"Generate client secret\") the Client Secret.",
            "Set AIRTABLE_BASE_ID to the base you want to sync (found in the API docs for your base).",
        ],
    },
    "linear": {
        "docs_url": "https://developers.linear.app/docs/oauth/authentication",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to linear.app/settings/api -> OAuth applications -> New.",
            "Paste the Redirect URL below.",
            "Scopes: read, write, issues:create.",
            "Copy the Client ID and Client Secret.",
            "Set LINEAR_TEAM_ID to the team where event issues should land (Settings -> My teams -> General -> ID).",
        ],
    },
    "asana": {
        "docs_url": "https://developers.asana.com/docs/oauth",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to app.asana.com/0/my-apps -> Create new app.",
            "Under \"OAuth\", paste the Redirect URL below.",
            "Copy the Client ID and Client Secret.",
            "Set ASANA_WORKSPACE_GID to the workspace you want issues to appear in (Admin console -> Workspace settings).",
        ],
    },
    "trello": {
        "docs_url": "https://trello.com/app-key",
        "redirect_hint": "Trello uses a power-up API key + token flow.",
        "steps": [
            "Go to trello.com/power-ups/admin and create a new Power-Up for your workspace.",
            "Copy the API key.",
            "Visit https://trello.com/1/authorize?expiration=never&name=SOMTool&scope=read,write&response_type=token&key=YOUR_API_KEY -- grant, copy the token.",
            "Paste both below. Set TRELLO_LIST_ID to the list ID new cards should land in.",
        ],
    },
    "clickup": {
        "docs_url": "https://clickup.com/api/developer-portal/authentication/",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Open app.clickup.com -> Settings -> Integrations -> ClickUp API.",
            "\"Create an App\" -> paste the Redirect URI below.",
            "Copy the Client ID + Client Secret.",
            "Set CLICKUP_LIST_ID to the List where event tasks should be created.",
        ],
    },
    "quickbooks": {
        "docs_url": "https://developer.intuit.com/app/developer/qbo/docs/get-started",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to developer.intuit.com -> My Apps -> Create an app -> QuickBooks Online and Payments.",
            "In Keys & OAuth, paste the Redirect URI below in \"Redirect URIs\".",
            "Copy the Client ID and Client Secret.",
            "Set QUICKBOOKS_REALM_ID to your company realm ID (visible once you connect to a sandbox or production company).",
        ],
    },
    "xero": {
        "docs_url": "https://developer.xero.com/documentation/guides/oauth2/auth-flow/",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to developer.xero.com/app/manage -> New app -> Web app.",
            "Paste the Redirect URI below.",
            "Scopes: accounting.transactions, accounting.contacts, offline_access.",
            "Copy the Client ID and Client Secret.",
            "XERO_TENANT_ID can be set later; SOMTool will pick the first connected tenant by default.",
        ],
    },

    # ── Social & Promo ─────────────────────────────────
    "buffer": {
        "docs_url": "https://buffer.com/developers/api/oauth",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to buffer.com/developers/apps -> Create app.",
            "Paste the Redirect URI (Callback URL) below.",
            "Copy the Client ID and Client Secret.",
        ],
    },
    "hootsuite": {
        "docs_url": "https://developer.hootsuite.com/docs/using-oauth-20",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Email developers@hootsuite.com to request a developer account (partner onboarding).",
            "Once approved, create an app in the Hootsuite developer portal.",
            "Paste the Redirect URI below.",
            "Copy the Client ID and Client Secret.",
        ],
    },
    "canva": {
        "docs_url": "https://www.canva.dev/docs/connect/",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to canva.com/developers -> Create an integration (requires Canva for Teams).",
            "Type: \"Connect API integration\".",
            "Paste the Redirect URL below.",
            "Scopes: design:read, design:write, folder:read.",
            "Copy the Client ID and Client Secret.",
        ],
    },
    "meta_graph": {
        "docs_url": "https://developers.facebook.com/apps/",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to developers.facebook.com/apps -> Create app -> Business.",
            "Add the \"Facebook Login\" product, open Settings, paste the Redirect URI below as a Valid OAuth Redirect URI.",
            "Add \"Instagram Graph API\" if you need IG cross-posting.",
            "Copy the App ID (Client ID) and App Secret.",
        ],
    },
    "linkedin_pages": {
        "docs_url": "https://www.linkedin.com/developers/apps",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to linkedin.com/developers/apps -> Create app, link it to your organization Page.",
            "Under Products, request \"Share on LinkedIn\" and \"Marketing Developer Platform\".",
            "Paste the Redirect URI below.",
            "Copy the Client ID + Client Secret.",
        ],
    },

    # ── Messaging ──────────────────────────────────────
    "discord": {
        "docs_url": "https://discord.com/developers/applications",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Go to discord.com/developers/applications -> New Application.",
            "OAuth2 tab: paste the Redirect URI below.",
            "Bot tab: add a Bot user; copy the Bot Token into DISCORD_BOT_TOKEN.",
            "Back on OAuth2 -> General, copy the Client ID and Client Secret.",
            "Invite the bot to your guild with the scopes bot + applications.commands.",
        ],
        "field_hints": {
            "DISCORD_BOT_TOKEN": "Bot tab -> Token -> Reset / Copy.",
        },
    },
    "whatsapp": {
        "docs_url": "https://www.twilio.com/docs/whatsapp/quickstart",
        "redirect_hint": "WhatsApp via Twilio uses Account SID + Auth Token (no OAuth).",
        "steps": [
            "Sign up at twilio.com and request WhatsApp sender access (or use the sandbox).",
            "Copy your Account SID and Auth Token from twilio.com/console.",
            "Set TWILIO_WHATSAPP_FROM to the approved sender number, formatted whatsapp:+1415..., or the sandbox number.",
        ],
        "field_hints": {
            "TWILIO_WHATSAPP_FROM": "Must include the whatsapp: prefix (e.g. whatsapp:+14155238886).",
        },
    },

    # ── Identity ───────────────────────────────────────
    "okta": {
        "docs_url": "https://developer.okta.com/docs/guides/implement-grant-type/authcode/main/",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "Sign in to your Okta admin -> Applications -> Create App Integration -> OIDC - OpenID Connect -> Web Application.",
            "Paste the Redirect URI below in \"Sign-in redirect URIs\".",
            "Grant types: Authorization Code + Refresh Token.",
            "Copy Client ID + Client Secret from the app's General tab.",
            "Set OKTA_DOMAIN to your Okta tenant (e.g. yourco.okta.com, no https://).",
        ],
        "field_hints": {
            "OKTA_DOMAIN": "Your tenant host, no protocol -- e.g. yourco.okta.com.",
        },
    },
}


def get(provider_slug: str) -> dict:
    """Return the setup doc for a slug, or a minimal empty-state dict."""
    return DOCS.get(provider_slug) or {
        "docs_url": "",
        "redirect_hint": _REDIRECT_NOTE,
        "steps": [
            "This provider hasn't been documented in-app yet.",
            "Paste whichever keys the provider supplies into the fields on the right.",
            "If the provider uses OAuth, copy the redirect URI below into its developer console.",
        ],
        "field_hints": {},
    }
