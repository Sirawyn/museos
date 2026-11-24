"""Command line tools.

  python -m app.cli create-admin <username>        first admin login (prints a temporary password)
  python -m app.cli reset-password <username>
  python -m app.cli create-api-key [name]          key for the DM bot
  python -m app.cli backup <dest.db>               consistent copy of the live database
  python -m app.cli backup-loop <dir> [days=30]    nightly copies into <dir>, keeping the last <days>
"""
from __future__ import annotations

import sqlite3
import sys

from . import auth, db
from .admin import temp_password


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd, args = argv[0], argv[1:]
    with db.session() as con:
        db.init(con)
        if cmd == "create-admin" and args:
            pw = temp_password()
            con.execute("INSERT INTO users(username, password_hash, role, created_at) VALUES (?,?,?,?) "
                        "ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash, role='admin', "
                        "active=1, must_change_password=1",
                        (args[0].lower(), auth.hash_password(pw), "admin", auth.iso(auth.now())))
            con.commit()
            print(f"Admin login: {args[0].lower()}\nTemporary password: {pw}\n(you'll pick your own at first login)")
        elif cmd == "reset-password" and args:
            pw = temp_password()
            n = con.execute("UPDATE users SET password_hash=?, must_change_password=1, active=1 WHERE username=?",
                            (auth.hash_password(pw), args[0])).rowcount
            con.commit()
            print(f"Temporary password for {args[0]}: {pw}" if n else "No such user")
        elif cmd == "create-api-key":
            print(auth.create_api_key(con, args[0] if args else "DM bot"))
        elif cmd == "backup" and args:
            dest = sqlite3.connect(args[0])
            con.backup(dest)
            dest.close()
            print(f"Backed up to {args[0]}")
        elif cmd == "backup-loop" and args:
            import time
            from datetime import date
            from pathlib import Path
            folder, keep = Path(args[0]), int(args[1]) if len(args) > 1 else 30
            folder.mkdir(parents=True, exist_ok=True)
            while True:
                dest = sqlite3.connect(str(folder / f"muse-{date.today().isoformat()}.db"))
                con.backup(dest)
                dest.close()
                for old in sorted(folder.glob("muse-*.db"))[:-keep]:
                    old.unlink()
                time.sleep(86400)
        else:
            print(__doc__)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
