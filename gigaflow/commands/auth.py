"""login / logout / whoami — email-only waitlist auth for the CLI."""
import webbrowser

from gigaflow import _auth, _fmt

_DEFAULT_BOOK_A_DEMO = "https://gigaflow.io/demo"


def register(sub) -> None:
    sub.add_parser("login", help="Sign in with your waitlist email").set_defaults(func=_handle_login)
    sub.add_parser("logout", help="Clear stored credentials").set_defaults(func=_handle_logout)
    sub.add_parser("whoami", help="Show the signed-in account").set_defaults(func=_handle_whoami)


def interactive_login(base_url: str) -> bool:
    """Prompt for the waitlist email and sign in. Returns True on success.

    Shared by `gigaflow login` and `gigaflow setup` (auto sign-in)."""
    _fmt.info("GigaFlow is invite-only. Sign in with the email you booked your demo with.")
    _fmt.info(f"No access yet? Book a demo: {_DEFAULT_BOOK_A_DEMO}")
    email = _fmt.prompt("Waitlist email", required=True)
    ok, info = _auth.login(base_url, email)
    if ok:
        _fmt.ok(f"Signed in as {info.get('email', email)}")
        return True
    if info.get("code") == "not_on_allowlist":
        url = info.get("book_a_demo_url", _DEFAULT_BOOK_A_DEMO)
        _fmt.fail("That email isn't on the waitlist yet — you need to book a demo to get access.")
        _fmt.info(f"Book a demo to get in: {url}")
        _fmt.info("Opening the booking page in your browser...")
        webbrowser.open(url)
        return False
    _fmt.fail(f"Login failed: {info.get('error', 'unknown error')}")
    return False


def ensure_authenticated(base_url: str, api_key: str | None = None) -> str | None:
    """Resolve a bearer credential for `setup`, signing in if needed.

    Order: an already-resolved key (dev --api-key/$GIGAFLOW_API_KEY, a prior
    `gigaflow login`, or saved config) → interactive email login. Returns the
    credential string, or None if sign-in failed."""
    if api_key:
        return api_key
    token = _auth.access_token(base_url)
    if token:
        return token
    _fmt.section("Sign in")
    if not interactive_login(base_url):
        return None
    return _auth.access_token(base_url)


def _handle_login(args, base_url: str) -> None:
    _fmt.header("GigaFlow Login")
    interactive_login(base_url)


def _handle_logout(args, base_url: str) -> None:
    _auth.clear_credentials()
    _fmt.ok("Signed out.")


def _handle_whoami(args, base_url: str) -> None:
    creds = _auth.load_credentials()
    if not creds:
        _fmt.info("Not signed in. Run: gigaflow login")
        return
    _fmt.info(f"Signed in as {creds.get('email', '(unknown email)')}")
