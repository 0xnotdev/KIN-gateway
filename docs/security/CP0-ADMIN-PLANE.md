# CP0 Admin-Plane Boundary

## Security contract

KIN exposes two independent ASGI applications. The data-plane application created by `create_gateway_app` defaults to public port `8080` and contains discovery and A2A routes only. The administration application created by `create_admin_app` defaults to `127.0.0.1:9090` and contains `/admin/*` routes only. The admin application is never mounted under the public application.

This is a deployment boundary as well as a routing convention. Production packaging must run the applications on separate listeners and keep `9090` on loopback or an explicitly private IP. A reverse proxy, service mesh, firewall, or Kubernetes NetworkPolicy must not publish the admin listener.

## Bootstrap authentication

CP0 supports either:

1. `authentication="token"` with `token_secret_ref` resolved from customer-local secret storage on each request. The caller sends `Authorization: Bearer <token>`. Comparison is constant-time. The token value is not part of settings, errors, or logs.
2. `authentication="mtls"`. The TLS-serving stack must require and validate a client certificate, then place its verified TLS object in the ASGI `ssl_object` scope extension. Missing certificate evidence fails closed. Do not use this mode behind a server that does not provide verified peer-certificate state.

The admin OpenAPI and interactive documentation endpoints are disabled. Every current and future administrative endpoint must remain below `/admin/`, where authentication middleware runs before routing.

## Required topology

```text
external A2A client -> 0.0.0.0:8080 -> public data-plane app -> private upstream
operator/private net -> 127.0.0.1:9090 -> authenticated admin app
```

Never reuse an external data-plane bearer, upstream service credential, or admin credential for another role. Sending an admin token to the data plane does not forward it upstream and does not authorize an A2A operation.

## Acceptance evidence

`tests/contract/test_admin_plane.py` proves:

- the public application returns `404` for `/admin/health`, even with the correct admin credential;
- missing, incorrect, and data-plane bearer values return `401` on the admin application;
- the correct bootstrap token succeeds;
- mTLS mode denies missing peer-certificate evidence and accepts verified evidence;
- the admin token canary is absent from upstream request headers and captured logs;
- the default ports are `8080` and `9090`, with loopback as the default admin bind.
