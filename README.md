# Google Trends India → Telegram Bot

This project checks Google Trends India for the past four hours, selects the
largest trends, takes one related news article supplied in the Trends RSS item,
and sends the result to Telegram.

## 1. Create the Telegram bot

1. Open Telegram and message `@BotFather`.
2. Send `/newbot`.
3. Follow the instructions and copy the bot token.
4. Open your new bot and press **Start**.
5. In a browser, open:

   `https://api.telegram.org/botYOUR_TOKEN/getUpdates`

6. Find `"chat":{"id":...}` and copy that number.

For a group, add the bot to the group, send a message in the group, then run
`getUpdates`. Group chat IDs normally begin with `-`.

## 2. Create the GitHub repository

1. Create a new GitHub repository.
2. Upload all files from this project, including the `.github` folder.
3. Open **Settings → Secrets and variables → Actions**.
4. Create these repository secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

Never paste the token directly inside `bot.py`.

## 3. Test it

Open **Actions → Send India Google Trends to Telegram → Run workflow**.

## Schedule

The workflow uses:

`0 */4 * * *`

GitHub cron uses UTC and runs approximately every four hours. Scheduled jobs can
occasionally start a little late.

## Change the number of keywords

In `.github/workflows/trends_bot.yml`, change:

`TOP_N: "5"`

Use `"1"` to send only the single highest-volume keyword.

## Run locally

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="your token"
export TELEGRAM_CHAT_ID="your chat id"
python bot.py
```

On Windows PowerShell:

```powershell
pip install -r requirements.txt
$env:TELEGRAM_BOT_TOKEN="your token"
$env:TELEGRAM_CHAT_ID="your chat id"
python bot.py
```

## Important limitation

Google's public Trends API is currently an alpha-access product. This free
project therefore uses the public Trending Now RSS endpoint. It may change in
the future, so the parser might eventually need an update.
