# Slack App Setup Guide

**⚠️ CRITICAL:** These slash commands MUST be configured in Slack for the Knowledge Base bot to work!

Without these commands registered, users will get errors like:
```
/create-knowledge is not a valid command
```

---

## Required Slack App Configuration

### Step 1: Go to Slack App Settings

1. Visit: https://api.slack.com/apps
2. Select your **Knowledge Base** app (or create new app)
3. Click **Slash Commands** in the left sidebar

---

## Slash Commands to Create

### 1. `/create-knowledge` ⚡ (REQUIRED)

**Purpose:** Allows users to add quick facts to the knowledge base

**Configuration:**
```
Command:           /create-knowledge

Request URL:       https://your-domain.com/slack/events
                   (Same as your bot's Event Subscriptions URL)

Short Description: Add a quick fact to the knowledge base

Usage Hint:        The admin of Snowflake is @sarah

Escape channels, users, and links: ✅ Checked
```

**Examples users will use:**
- `/create-knowledge The admin of Snowflake is @sarah`
- `/create-knowledge To request AWS access, ask in #platform-access`
- `/create-knowledge Weekly standup is at 9am in #engineering-standup`

---

### 2. `/ingest-doc` 📥 (REQUIRED)

**Purpose:** Import external documents (PDFs, Google Docs, web pages) into knowledge base

**Configuration:**
```
Command:           /ingest-doc

Request URL:       https://your-domain.com/slack/events
                   (Same as your bot's Event Subscriptions URL)

Short Description: Import external documents into the knowledge base

Usage Hint:        https://docs.company.com/guide.pdf

Escape channels, users, and links: ✅ Checked
```

**Examples users will use:**
- `/ingest-doc https://docs.company.com/guide.pdf`
- `/ingest-doc https://docs.google.com/document/d/xxx`
- `/ingest-doc https://wiki.company.com/runbooks`

**Supported sources:**
- PDF files
- Google Docs (public)
- Web pages
- Notion pages (public)

---

### 3. `/create-doc` 📝 (OPTIONAL - AI Document Creation)

**Purpose:** Create formal documentation with AI assistance

**Configuration:**
```
Command:           /create-doc

Request URL:       https://your-domain.com/slack/events
                   (Same as your bot's Event Subscriptions URL)

Short Description: Create a formal document with AI assistance

Usage Hint:        (opens a form)

Escape channels, users, and links: ✅ Checked
```

**Usage:**
- User runs `/create-doc`
- Modal opens with form
- AI helps generate structured documentation

---

### 4. `/help` ❓ (RECOMMENDED)

**Purpose:** Show help information about the Knowledge Base bot

**Configuration:**
```
Command:           /help

Request URL:       https://your-domain.com/slack/events
                   (Same as your bot's Event Subscriptions URL)

Short Description: Show Knowledge Base bot help

Usage Hint:        (no parameters)

Escape channels, users, and links: ✅ Checked
```

**Usage:**
- `/help` - Show overview
- `/help create` - Help on creating knowledge
- `/help ingest` - Help on importing documents
- `/help feedback` - Help on providing feedback

---

## Step 2: Save Each Command

After creating each command:
1. Click **Save** at the bottom
2. **Important:** You'll see a yellow banner saying "Reinstall your app"
3. Click **Reinstall to Workspace** (or reinstall will happen automatically)

---

## Step 3: Verify Installation

### Test in Slack:

```
/create-knowledge Test fact - the bot should respond
/ingest-doc https://example.com - bot should acknowledge
/help - should show help message
```

**If you see "is not a valid command" → Command not registered!**

---

## Required Slack Permissions (OAuth Scopes)

Your bot needs these permissions to work:

### Bot Token Scopes:
```
✅ app_mentions:read     - Receive @bot mentions
✅ channels:history      - Read channel messages
✅ channels:read         - Read public channel info
✅ chat:write           - Send messages
✅ commands             - Receive slash commands
✅ im:history           - Read DM history
✅ im:read              - Read DM info
✅ im:write             - Send DMs
✅ reactions:write      - Add reactions to messages
✅ users:read           - Read user info
✅ users:read.email     - Read user emails (for owner notifications)
```

**To add scopes:**
1. Go to **OAuth & Permissions** in Slack app settings
2. Scroll to **Scopes**
3. Add each scope listed above
4. **Reinstall app** after adding scopes

---

## Event Subscriptions

**Enable Events:** ✅ ON

**Request URL:** `https://your-domain.com/slack/events`

**Subscribe to Bot Events:**
```
✅ app_mention          - When someone @mentions the bot
✅ message.channels     - Messages in channels bot is in
✅ message.im           - Direct messages to bot
✅ reaction_added       - When reactions added to messages
```

---

## Interactivity & Shortcuts

**Enable Interactivity:** ✅ ON

**Request URL:** `https://your-domain.com/slack/events`

**Message Shortcuts to Create:**

### "Save as Doc" Shortcut

```
Name:           Save as Doc
Short Description: Convert this Slack thread into documentation
Callback ID:    save_thread_as_doc
```

This allows users to:
1. Right-click any message
2. Click "More actions" → "Save as Doc"
3. Convert thread to structured documentation

---

## Admin Channel Setup (Information Guardian)

The bot sends admin escalations to a dedicated channel when knowledge gets negative feedback.

### Create Admin Channel:

1. **Create channel:** `#knowledge-admins` (or your preferred name)
2. **Add the bot:** Invite @knowledge-base to the channel
3. **Set environment variable:**
   ```bash
   # In your .env file
   ADMIN_CHANNEL_ID=C0A6WU7EFMY  # Your channel ID
   ```

**To get channel ID:**
1. Open channel in Slack
2. Click channel name at top
3. Scroll down to "Channel ID" → Copy
4. Or right-click channel → "Copy link" → ID is in URL

---

## Environment Variables Needed

Create `.env` file with:

```bash
# Slack Configuration
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret
SLACK_APP_TOKEN=xapp-your-app-token  # For Socket Mode

# Admin Channel (for Information Guardian)
ADMIN_CHANNEL_ID=C0A6WU7EFMY  # Replace with your channel ID

# Optional: Owner Notification Email Domain
OWNER_EMAIL_DOMAIN=company.com  # For looking up content owners

# Database
DATABASE_URL=sqlite+aiosqlite:///./knowledge_base.db

# ChromaDB
CHROMA_HOST=localhost
CHROMA_PORT=8000

# LLM Provider
LLM_PROVIDER=anthropic  # or openai, bedrock
ANTHROPIC_API_KEY=your-key  # If using Anthropic
```

**Get Slack tokens from:**
- Bot Token: **OAuth & Permissions** → "Bot User OAuth Token"
- Signing Secret: **Basic Information** → "Signing Secret"
- App Token: **Basic Information** → "App-Level Tokens" → Create token with `connections:write`

---

## Deployment Checklist

Before deploying, verify:

### Slack App Configuration:
- [ ] All 4 slash commands created (`/create-knowledge`, `/ingest-doc`, `/create-doc`, `/help`)
- [ ] All OAuth scopes added
- [ ] Event Subscriptions enabled with correct URL
- [ ] Interactivity enabled with correct URL
- [ ] "Save as Doc" shortcut created
- [ ] App reinstalled after all changes

### Channel Setup:
- [ ] Admin channel created (e.g., `#knowledge-admins`)
- [ ] Bot added to admin channel
- [ ] Admin channel ID in environment variables

### Environment Variables:
- [ ] `SLACK_BOT_TOKEN` set
- [ ] `SLACK_SIGNING_SECRET` set
- [ ] `SLACK_APP_TOKEN` set
- [ ] `ADMIN_CHANNEL_ID` set
- [ ] Database URL configured
- [ ] ChromaDB configured
- [ ] LLM API key set

### Testing:
- [ ] Run `/create-knowledge Test` - should work
- [ ] Run `/help` - should show help
- [ ] Run `/ingest-doc https://example.com` - should acknowledge
- [ ] @mention bot with question - should respond
- [ ] Send DM to bot - should respond
- [ ] Test feedback buttons - should appear on bot responses
- [ ] Test admin escalation - negative feedback goes to admin channel

---

## Troubleshooting

### "Command not valid" error
**Problem:** Slash command not registered in Slack
**Fix:** Create the command in Slack app settings → Reinstall app

### "The request to the Slack API failed: not_in_channel"
**Problem:** Bot not added to admin channel
**Fix:** Invite bot to `#knowledge-admins` channel

### Bot doesn't respond to @mentions
**Problem:** Missing scopes or events
**Fix:** Add `app_mentions:read` scope and `app_mention` event

### Feedback buttons don't appear
**Problem:** Interactivity not enabled
**Fix:** Enable Interactivity with correct Request URL

### Owner notifications don't work
**Problem:** Missing `users:read.email` scope
**Fix:** Add scope → Reinstall app

---

## Quick Setup Summary

**Minimum required for basic functionality:**

1. **3 Essential Commands:**
   - `/create-knowledge` - Add facts
   - `/ingest-doc` - Import docs
   - `/help` - Get help

2. **Essential Scopes:**
   - `app_mentions:read`
   - `chat:write`
   - `commands`
   - `channels:history`

3. **Event Subscriptions:**
   - `app_mention`
   - `message.channels`

4. **Admin Channel:**
   - Create `#knowledge-admins`
   - Add bot to channel
   - Set `ADMIN_CHANNEL_ID` env var

---

## E2E Test Verification

After setup, run E2E tests to verify:

```bash
cd /home/coder/Devel/keboola/ai-based-knowledge

# Set up E2E environment
cp .env .env.e2e
# Edit .env.e2e with test channel IDs

# Run E2E tests
./run_e2e_tests.sh

# Should see:
# ✅ Admin Escalation: PASSED
# ✅ Feedback Buttons: PASSED
# ✅ Information Guardian: PASSED
```

**If tests fail → Check this setup guide!**

---

## Support

If you encounter issues:

1. Check Slack app logs: **Event Subscriptions** → "Recent Events"
2. Check bot logs: Look for errors in application logs
3. Verify all checklist items above
4. Test each command manually in Slack
5. Run E2E tests to identify specific failures

---

**Remember:** Every time you change Slack app configuration, you MUST reinstall the app!
