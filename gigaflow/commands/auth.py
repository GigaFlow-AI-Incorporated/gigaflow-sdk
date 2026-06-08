"""login / logout / whoami — email-only waitlist auth for the CLI."""
import webbrowser

from gigaflow import _auth, _fmt

_DEFAULT_BOOK_A_DEMO = "https://gigaflow.io/demo"


def register(sub) -> None:
    sub.add_parser("login", help="Sign in with your waitlist email").set_defaults(func=_handle_login)
    sub.add_parser("logout", help="Clear stored credentials").set_defaults(func=_handle_logout)
    sub.add_parser("whoami", help="Show the signed-in account").set_defaults(func=_handle_whoami)


def _handle_login(args, base_url: str) -> None:
    _fmt.header("GigaFlow Login")
    _fmt.info("GigaFlow is invite-only. Sign in with the email you booked your demo with.")
    _fmt.info(f"No access yet? Book a demo: {_DEFAULT_BOOK_A_DEMO}")
    email = _fmt.prompt("Waitlist email", required=True)
    ok, info = _auth.login(base_url, email)
    if ok:
        _fmt.ok(f"Signed in as {info.get('email', email)}")
        return
    if info.get("code") == "not_on_allowlist":
        url = info.get("book_a_demo_url", _DEFAULT_BOOK_A_DEMO)
        _fmt.fail("That email isn't on the waitlist yet — you need to book a demo to get access.")
        _fmt.info(f"Book a demo to get in: {url}")
        _fmt.info("Opening the booking page in your browser...")
        webbrowser.open(url)
        return
    _fmt.fail(f"Login failed: {info.get('error', 'unknown error')}")


def _handle_logout(args, base_url: str) -> None:
    _auth.clear_credentials()
    _fmt.ok("Signed out.")


def _handle_whoami(args, base_url: str) -> None:
    creds = _auth.load_credentials()
    if not creds:
        _fmt.info("Not signed in. Run: gigaflow login")
        return
    _fmt.info(f"Signed in as {creds.get('email', '(unknown email)')}")
