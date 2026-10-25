"""
Send ONE test push notification to a participant's phone, shaped exactly like the engine's real ones
(a notification plus the experimentId / conversationId data), so the app's notification handling can be tested
without waiting for the scheduler.

It only READS the database (to find the participant's push token and their most recent conversation). It does not
create conversations, change the greeting, or write a log row.

Run from the logic-python folder, with the same .env the engine uses:

    .venv\\Scripts\\python.exe tools\\send_test_push.py --username dana                 (shows what it would send)
    .venv\\Scripts\\python.exe tools\\send_test_push.py --username dana --send          (really sends it)

Options:
    --experiment <id>     needed only if the same username exists in more than one experiment
    --text "..."          the notification text (default: a short test sentence)
    --no-conversation     send without a conversation id (the tap then opens the study home)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# The engine prints emoji; a Windows console using cp1252 would crash on them.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv

load_dotenv()

from bson import ObjectId  # noqa: E402

from core.models import UserContext  # noqa: E402
from utils.mongodb_client import mongodb_client  # noqa: E402


def find_user(username, experiment_id):
    query = {"username": username}
    if experiment_id:
        query["experimentId"] = {"$in": [experiment_id, ObjectId(experiment_id)]}
    users = list(mongodb_client.db[mongodb_client.users_collection].find(query))
    if not users:
        sys.exit(f"No participant named '{username}' was found.")
    if len(users) > 1:
        ids = ", ".join(str(u.get("experimentId")) for u in users)
        sys.exit(f"'{username}' exists in several experiments ({ids}); pass --experiment <id>.")
    return users[0]


def latest_conversation_id(user):
    meta = mongodb_client.db["metadata_conversations"].find_one(
        {"userId": str(user["_id"])}, sort=[("createdAt", -1)]
    )
    return str(meta["_id"]) if meta else None


def main():
    parser = argparse.ArgumentParser(description="Send one test push to a participant's phone.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--experiment")
    parser.add_argument("--text", default="Test message from Lexi: tap to open the conversation.")
    parser.add_argument("--no-conversation", action="store_true")
    parser.add_argument("--send", action="store_true", help="really send it (without this it only shows what it would do)")
    args = parser.parse_args()

    if not mongodb_client.connect():
        sys.exit("Could not connect to MongoDB (check MONGODB_URL in logic-python/.env).")

    user = find_user(args.username, args.experiment)
    token = user.get("fcmToken")
    if not token:
        sys.exit("This participant has no push token yet. Log in inside the app first, then try again.")

    experiment_id = str(user.get("experimentId", ""))
    conversation_id = None if args.no_conversation else latest_conversation_id(user)
    data = {}
    if conversation_id and experiment_id:
        data = {"conversationId": conversation_id, "experimentId": experiment_id}

    print(f"Participant : {args.username}  (experiment {experiment_id})")
    print(f"Push token  : {token[:8]}... ({len(token)} characters)")
    print(f"Text        : {args.text}")
    print(f"Opens       : {'conversation ' + conversation_id if data else 'the study home (no conversation id)'}")

    if not args.send:
        print("\nNothing was sent. Add --send to send it.")
        return

    from services.fcm_service import FCMService

    result = FCMService(dry_run=False).send_to_user(
        user=UserContext(user_id=str(user["_id"]), name=args.username, fcm_token=token),
        body=args.text,
        title="Lexi",
        extra_data=data or None,
    )
    print(f"\nSent. Firebase message id: {result}")


if __name__ == "__main__":
    main()
