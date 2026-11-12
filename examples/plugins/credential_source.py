"""Add a credential source.

To add a credential source you use the decorator `@plugins.credential_source("name")` on top of a class.

The class has:

* An `__init__` that takes the configuration of the source, as keyword arguments.
* `apply(method, url, headers, body=b"")`, which receives the request and returns the headers with the authentication added.
* It leaves the `headers` it received untouched and returns a new dict.

`skye.credential_source("name", **config)` builds it, as it builds the built-in sources.
"""

from collections.abc import Mapping

import skye

plugins = skye.Plugins()


@plugins.credential_source("vault-token")
class VaultTokenAuthenticator:
    def __init__(self, token: str) -> None:
        self._token = token

    def apply(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes = b""
    ) -> dict[str, str]:
        return {**headers, "X-Vault-Token": self._token}


def main() -> None:
    authenticator = skye.credential_source("vault-token", token="demo")
    headers = authenticator.apply(
        "GET", "https://api.example.com/v1/models", {"Accept": "application/json"}
    )
    print("headers added:", sorted(set(headers) - {"Accept"}))


if __name__ == "__main__":
    main()
