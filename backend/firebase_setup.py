import os

try:
    import firebase_admin
    from firebase_admin import credentials, auth as firebase_auth
except ImportError:
    firebase_admin = None
    credentials = None
    firebase_auth = None

_initialized = False


def init_firebase():
    global _initialized
    if _initialized:
        return

    if firebase_admin is None or credentials is None:
        print("WARNING: firebase-admin not installed. Auth will use dev mode.")
        _initialized = True
        return

    creds_json = os.environ.get("FIREBASE_CREDENTIALS")
    if creds_json:
        import json
        cred = credentials.Certificate(json.loads(creds_json))
        firebase_admin.initialize_app(cred)
        _initialized = True
        print("Firebase Admin SDK initialized from env")
    else:
        print("WARNING: Firebase credentials not found. Auth will use dev mode.")
        _initialized = True  # Mark as initialized to avoid retrying


def verify_firebase_token(id_token: str) -> dict | None:
    if firebase_auth is None:
        return None
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        return decoded
    except Exception:
        return None
