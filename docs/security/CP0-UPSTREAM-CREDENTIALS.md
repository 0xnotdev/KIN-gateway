# CP0 Upstream Credential Contract

External caller authority and customer-local upstream authority are separate trust domains. The external `Authorization` header is never present in the credential-provider context and is not part of the allowlisted A2A headers forwarded upstream.

The stable CP0 seam is:

```python
class UpstreamCredentialProvider(Protocol):
    async def headers_for(
        self,
        request_context: RequestContext,
    ) -> Mapping[str, str]: ...
```

`RequestContext` contains only the upstream HTTP method and URL. CP0 has exactly three implementations:

- `NoCredentialProvider` for a private unauthenticated upstream;
- `StaticHeaderCredentialProvider` for an explicitly injected customer-owned static value;
- `SecretBackedCredentialProvider` for a configured header whose value is resolved from customer-local secret storage per request.

Credential providers cannot own A2A framing headers such as `Host`, `Content-Type`, `Content-Length`, `A2A-Version`, or `A2A-Extensions`. Header names and values reject invalid tokens and line breaks. Missing or empty secrets fail before the upstream request.

Workload federation, OAuth token exchange, Azure OBO, SPIFFE, and dynamic Vault credentials remain outside CP0 and require a later scope decision.
