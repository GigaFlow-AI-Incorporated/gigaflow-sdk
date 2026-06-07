"""login / logout / whoami — per-user Supabase identity for the CLI."""
from gigaflow import _auth, _fmt


def register(sub) -> None:
    sub.add_parser("login", help="Sign in via the browser and store credentials").set_defaults(func=_handle_login)
    sub.add_parser("logout", help="Clear stored credentials").set_defaults(func=_handle_logout)
    sub.add_parser("whoami", help="Show the signed-in account").set_defaults(func=_handle_whoami)


def _handle_login(args, base_url: str) -> None:
    _fmt.header("GigaFlow Login")
    creds = _auth.run_loopback_login(base_url)
    if not creds:
        _fmt.fail("Login was not completed.")
        _fmt.info("Sign up or sign in at https://api.gigaflow.io, then run: gigaflow login")
        return
    _fmt.ok(f"Signed in as {creds.get('email', 'your account')}")


def _handle_logout(args, base_url: str) -> None:
    _auth.clear_credentials()
    _fmt.ok("Signed out.")


def _handle_whoami(args, base_url: str) -> None:
    creds = _auth.load_credentials()
    if not creds:
        _fmt.info("Not signed in. Run: gigaflow login")
        return
    _fmt.info(f"Signed in as {creds.get('email', '(unknown email)')}")
