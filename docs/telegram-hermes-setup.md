# Hermes and Telegram

ERMCLIP is registered as an external Hermes skill. All editing and model reasoning run on this PC. Telegram messages use Telegram's network. Source video, audio and transcript files stay local. Media upload is off.

## Local model

Run `scripts/configure-hermes-local.py` with the project Python to configure Hermes through its own supported config writer. The script makes a private configuration backup in `state`, pins the main model and auxiliary tasks to Qwen3.5 9B at `127.0.0.1:8088`, and clears model fallback lists. The local authentication key stays in Hermes `.env`; it is not stored in job profiles or printed. Unsupported vision calls fail locally. Automatic background review and title generation are off.

This Hermes build requires at least 64,000 context tokens. The shared local server uses 65,536 tokens and one request slot. Editing and Hermes requests share that slot. The worker can stop the model briefly while it runs GPU transcription; Hermes must retry after that phase.

Start a new Hermes chat after this change. Existing sessions can retain their previous model selection. Use `/model` to check that the current session uses `ermclip_local` and `ermclip-qwen35-9b` before an editing command.

## Complete Telegram setup

1. In Hermes Messaging → Telegram, enter the bot token for `@hermes_2eq47xdksbp5xcxn_bot`. Do not paste it into this chat or a terminal command.
2. Set **Allowed users** to your numeric Telegram user ID. Do not enable access for all users.
3. Open the bot in Telegram and press **Start**. This permits a direct reply to your account.
4. Run `scripts/connect-telegram.ps1 -UserId <your numeric ID>`. This verifies the bot name, verifies your ID against the Hermes allowlist, sends one connection check to your private chat, enables notifications, and restarts the worker. It does not send historical events.
5. In Hermes Messaging, start the existing gateway. Do not start a second Telegram listener. Send `/ermclip Check the worker health and show the job status` to the bot.

Alternative owner setup: with the Hermes gateway running in its default pairing policy, press **Start** in the bot and send the returned eight-character pairing code to the local operator. The operator approves that exact code with `hermes pairing approve telegram <code>`, reads the approved account ID, and sets the same ID in the Telegram allowlist before running the connection script. Never approve the first pending account without the owner's code or account confirmation.

The skill takes the sender ID from trusted Hermes gateway context and passes it to the ERMCLIP CLI. Commands from an ID outside the allowlist are refused. Use `/ermclip` for editing, caption styles, status, feedback, and revisions. Submit work to the queue; do not hold a Telegram conversation open during a full render.

Hermes permits the exact local read-only worker health command. Editing commands still use Hermes' normal terminal approval flow. Approve the specific requested job when the gateway shows its command card.

`scripts/ermclip.ps1 telegram-status` shows readiness without printing the token. Bot verification alone does not prove incoming command delivery. A real Telegram command must reach Hermes and return the actual worker result to complete that test.

The bot token has been stored in Hermes and its bot identity was verified. The Telegram adapter reached `connected`, then the gateway was stopped at the owner's request. The local editing worker remains running. Owner authorisation and an incoming authorised command test remain pending. The owner can supply a numeric user ID or the bot's pairing code after turning the gateway on. A bot username alone is insufficient.
