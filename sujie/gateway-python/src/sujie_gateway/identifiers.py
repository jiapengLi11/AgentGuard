"""Process-local identifiers shared by the gateway and in-memory provenance store."""

import os
import time

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id() -> str:
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(CROCKFORD[(value >> (5 * (25 - i))) & 31] for i in range(26))
