# Priority 1 production QA smoke

The signed-in smoke is limited to a dedicated QA account and workspace. It creates one synthetic BOM analysis and one **Hold for review** decision so saved reports, exports, compare, and decisions can be checked together.

The runner never sends email, changes email or supplier-check preferences, refreshes supplier data, or approves a replacement. It leaves the synthetic report and hold decision in the QA workspace for review. The optional `--free-audit` path submits a six-part synthetic BOM to the public audit and checks the five-result preview; it does not submit the email form.

## Production prerequisites

- Create and verify a dedicated QA account. Do not use a customer or personal workspace.
- Put the verified QA email in the API service's `CADIVOR_PUBLIC_BOM_QA_EMAILS` allowlist if using `--free-audit`.
- Get the QA workspace ID from the signed-in session or admin workspace view.
- Run from a secure local shell with `apps/web` dependencies installed. Keep the password in an environment variable or secret manager; never add it to the repository or command history.

```bash
export CADIVOR_P1_QA_EMAIL='qa-address@example.com'
export CADIVOR_P1_QA_PASSWORD='read-from-your-secret-manager'
export CADIVOR_P1_QA_WORKSPACE_ID='the-dedicated-qa-workspace-id'
export CADIVOR_P1_WRITE_ACK='I_ACKNOWLEDGE_SYNTHETIC_WRITES_TO_THE_QA_WORKSPACE'
npm run smoke:priority1:production --prefix apps/web
```

To also exercise the public five-result free audit, append `-- --free-audit`. That upload creates a public synthetic audit record but does not request full-report email verification.

The runner checks the signed-in session's workspace ID before its first write. A missing/mismatched QA workspace or missing acknowledgement stops the run before test data is created. Use only the QA account because report exports, alternate search, and the Hold for review decision operate on saved test data.
