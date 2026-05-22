"""Slack bot entry point for the university NL query engine.

Listens for @mentions in channels and direct messages, runs the NL→SPARQL+SQL
pipeline, and posts the generated queries and results back in a thread.

Run with:
    python src/slack_bot.py
"""

import os
import sys
import threading
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

sys.path.insert(0, os.path.dirname(__file__))
import nl_translator
import sparql_executor
import sql_executor

load_dotenv()

app = App(token=os.environ["SLACK_BOT_TOKEN"])


def _df_to_slack(df) -> str:
    if df is None or df.empty:
        return "_No results_"
    return "```\n" + df.to_string(index=False) + "\n```"


def _answer(question: str, say, thread_ts=None):
    kwargs = {"thread_ts": thread_ts} if thread_ts else {}

    say(text=f":hourglass_flowing_sand: Translating: _{question}_", **kwargs)

    try:
        sparql_q, sql_q = nl_translator.translate(question)
    except Exception as exc:
        say(text=f":x: Translation failed: {exc}", **kwargs)
        return

    sparql_df = sql_df = sparql_err = sql_err = None

    def run_sparql():
        nonlocal sparql_df, sparql_err
        try:
            sparql_df = sparql_executor.execute(sparql_q)
        except Exception as exc:
            sparql_err = str(exc)

    def run_sql():
        nonlocal sql_df, sql_err
        try:
            sql_df = sql_executor.execute(sql_q)
        except Exception as exc:
            sql_err = str(exc)

    t1 = threading.Thread(target=run_sparql)
    t2 = threading.Thread(target=run_sql)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    sparql_result = _df_to_slack(sparql_df) if not sparql_err else f":warning: {sparql_err}"
    sql_result = _df_to_slack(sql_df) if not sql_err else f":warning: {sql_err}"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": question[:150]},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*SPARQL Query*\n```{sparql_q}```"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*SPARQL Results*\n{sparql_result}"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*SQL Query*\n```{sql_q}```"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*SQL Results*\n{sql_result}"},
        },
    ]

    say(blocks=blocks, text=question, **kwargs)


@app.event("app_mention")
def handle_mention(event, say):
    question = event["text"].split(">", 1)[-1].strip()
    if question:
        _answer(question, say, thread_ts=event["ts"])


@app.event("message")
def handle_dm(event, say):
    if event.get("channel_type") == "im" and not event.get("bot_id"):
        _answer(event["text"], say)


if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    print("University bot is running. Press Ctrl+C to stop.")
    handler.start()
