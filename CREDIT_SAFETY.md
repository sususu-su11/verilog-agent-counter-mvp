# Vultr Credit Safety: No implied financial hard cap

- `MOCK_LLM=1` is the default for private acceptance; it makes **zero** inference API calls.
- No live Vultr requests were executed as part of this patch delivery.
- For live usage, an operator must explicitly set `MOCK_LLM=0`, a Vultr key, `LIVE_INFERENCE_MAX_CALLS>0` and a persistent writable inference ledger (`INFERENCE_LEDGER_PATH=/state/quota.sqlite` in compose).
- Every attempted live call consumes one durable allowance **before** HTTP requests. The allowance cannot be raised silently by changing `.env`; the persisted limit must undergo a deliberate operator review. The maximum number of heal attempts is four.
- **This is not a monetary spending cap.** One inference request may cost a variable amount, VM/build/network charges are outside this allowance, and the account's remaining promotional credit is not detectable here. Only Vultr's account-side hard billing controls (if available and verified) can provide a strict protection against charging a linked card.
- **Do not enable live mode or provision a paid VM unless the owner confirms that the provider's charging behavior cannot exceed the allowed remaining credit.** If this cannot be confirmed, use mock mode offline and do not claim a credit-only guarantee.
- No automatic cloud resource provisioning, payment changes, live inference smoke tests or remote deployments are performed by the scripts in this patch.
