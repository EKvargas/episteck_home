# Olin Finance local conversational pilot

This pilot gives Olin Finance its own SQLite inbox and append-only financial events. It does not use Hermes memory as a ledger. There is no Finance deployment, WhatsApp pairing, OpenClaw change, bank connection, or real family data here.

## Run the synthetic conversation

From the repository root, with Python 3.11 or newer:

```powershell
python services/finance/examples/run_synthetic.py --db "$env:TEMP/olin-finance-pilot.sqlite"
```

The command prints every synthetic message, Olin's record/clarification result, the private debt answer, and the resulting records. Run it **again with the same DB path**: recorded events remain unchanged. Use another path for a fresh demonstration. The example uses isolated `PSN-...-SYNTHETIC` identities and a test-only authorizer in the example file; the Finance package has no synthetic authorization fallback.

The three SVG files are synthetic screenshots. The example extracts their visible text as a stand-in for OCR, saves each attachment path and SHA-256 digest, and sends the text through the same `TrustedMessage` intake contract as ordinary messages. This proves routing, ambiguity and duplicate behavior; it does **not** prove OCR accuracy or a real bank receipt. `bank_statement` is a synthetic evidence label in this demonstration.

## Intake and Hermes boundary

1. A trusted channel adapter resolves the sender to a known Person and stores `TrustedMessage(channel, message_id, sender_id, sender_name, chat_id, chat_scope, text, attachment_ref, attachment_sha256, evidence_kind)`. IDs supplied to Finance must be unique across that adapter's channels. Untrusted model output cannot create this envelope.
2. Hermes receives the source ID and can call only `record_finance_message(source_message_id)` or `answer_finance_question(source_message_id)` from `finance_pilot.mcp.create_mcp`. No tool accepts sender, actor, chat scope, attachment hash, delegation, SQL, credentials, or a payment instruction. The delegation is read only from the FastMCP HTTP transport header.
3. Finance independently checks the configured owner's `FINANCE/CREATE` or `FINANCE/VIEW` permission against Home. `HomeFinanceAuthorizer` uses the existing one-request `check_access` shape and fails closed. The local example substitutes isolated test identities because live Home authorization could not be reached.
4. A clear supported statement records its fact immediately. Missing request IDs, conflicting people/amounts, an early debt agreement, or an unclear screenshot returns one short clarification. Planned or reported payments are never verified receipts. A receipt must have a trusted `bank_statement` evidence label, attachment digest and unique bank reference, and cannot allocate more than the receipt or outstanding debt.
5. Queries run only from the owner's private chat. Group requests may enter the inbox and create authorized case facts, but no household balance or debt answer is returned to a group. Message ID, sender and attachment provenance stay in `inbox`; financial changes and corrections stay in append-only `events`. Replaying a source ID, reusing an attachment digest, or reusing a receipt reference does not apply another financial effect.

The parser is intentionally a **small pilot vocabulary**, demonstrated in `examples/run_synthetic.py`. It resolves ordinary references such as “Rosa” to a request only when exactly one eligible request matches; otherwise it asks which one. Routine messages do not need internal request IDs or a form. It does not claim general natural-language extraction. Hermes can route normal messages to the tool; unsupported wording produces a clarification instead of a speculative record. A live adapter must bind sender identity and OCR output outside the model and prevent forged evidence labels.

## Tests

The shared local Python environment currently has FastMCP 4.0.3 with incompatible `mcp` 1.30.0. This command uses an isolated Python 3.13 package environment without changing that shared installation:

```powershell
$env:PYTHONPATH='services/finance'
uv run --no-project --python 3.13 --with fastmcp==4.0.3 --with pytest --with pytest-asyncio python -m pytest -q services/finance/tests
```

Tests cover the complete exchange, two requests/one funding payment, delivery plus recipient confirmation before a later USD agreement, partial verified allocation, reported versus verified repayment, an ambiguous screenshot, attachment and bank-reference duplicates, correction history, unauthorized reads/writes, private-only answers, restart/replay, and an in-process MCP protocol call using a test-only delegated identity.

## WhatsApp first; live gates

The [current official Hermes WhatsApp guide](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/whatsapp) describes a built-in Baileys bridge that uses a WhatsApp Web session, and a separate [Business Cloud API option](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/whatsapp-cloud). The repository's last validated Hermes version/configuration is **0.21.2**, with Home and Nutrition MCP through the delegated gateway ([G1.6 evidence](../../docs/architecture/G1_6_VALIDATION.md)); the current server could not be reached for a fresh check, and the current online guide is not proof of its exact installed behavior. Telegram remains a fallback.

Before a live pilot: verify the running home-agent version and channel config read-only; decide which WhatsApp adapter and number to use; map WhatsApp sender and group identifiers to Home Person identities; obtain explicit family participation and decide group/private reply routing; add a trusted media/OCR ingress with attachment storage; add Finance's Home delegation audience, service principal, gateway route and independent policy checks; prove access denial, replay, correction and no-group-leak on staging; then pair a dedicated chat only after review. Existing OpenClaw operations stay separate. None of these live steps was performed here.
