from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import os
import socket
import traceback
from urllib.parse import urlparse

from supabase import create_client


def main() -> None:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

    host = urlparse(url).hostname
    print("SUPABASE_URL:", url)
    print("host:", host)
    if host:
        print("getaddrinfo sample:", socket.getaddrinfo(host, 443)[:1])

    sb = create_client(url, key)
    print("client created")

    try:
        res = sb.auth.sign_up(
            {
                "email": "debug_dns@example.com",
                "password": "P@ssw0rd!123",
                "options": {"data": {"DisplayName": "dbg"}},
            }
        )
        print("sign_up done; user?", res.user is not None)
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    main()

