# Security policy

## Supported versions

`main` is the supported branch. Fixes land there first; older commits are not
maintained.

## Reporting a vulnerability

Please do **not** open a public issue. Use GitHub's private vulnerability
reporting:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Include the affected command or module, the input, the observed output, and
   any relevant endpoint.

If private reporting is unavailable, contact the maintainer through the
repository owner's GitHub profile.

## Scope

This project runs local scripts that call public data.gov.hk endpoints. It does
not store credentials, user accounts, or personal data. The main risks are:

- a command that echoes a secret from the environment;
- a malicious or malformed response from a data source;
- a path or shell injection through a command argument.

Please report those privately. Data-accuracy issues are not security issues;
open a normal issue or add them to `docs/BACKLOG.md` instead.
