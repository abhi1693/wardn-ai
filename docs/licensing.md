# Licensing

Wardn Community uses compiled entitlement ceilings. A licensed installation periodically
exchanges an opaque activation key for an Ed25519-signed, instance-bound entitlement lease.
Database resource limits are operator policy and can only tighten the signed ceiling.

## Backend configuration

```dotenv
WARDN_LICENSING_ACTIVATION_KEY=wardn_lic_...
WARDN_LICENSING_INSTANCE_NAME=production-eu
WARDN_LICENSING_RENEWAL_INTERVAL_SECONDS=3600
```

The backend pins `https://license.wardnai.dev`, the official issuer and audience, and the
official Ed25519 public key in source. There is no deployment setting that can redirect the
licensing authority or replace its verification key. The backend renews on startup and at the
configured interval. If renewal fails, the current
lease remains active until its signed expiry, then enters its signed grace window. Once grace
ends, Wardn falls back to Community ceilings without deleting or hiding existing data.

Superusers can inspect status with `GET /api/v1/license`, trigger renewal with
`POST /api/v1/license/renew`, or import a compact signed lease with
`PUT /api/v1/license/lease`.

Disconnected installations renew from a connected machine using their stable `instanceId` and
activation key plus their current rotating renewal token, then import both the returned
short-lived lease and replacement renewal token. There is no permanent offline license format.

The first activation consumes a licensed seat and receives a per-instance renewal token. Every
renewal atomically invalidates that token and returns its replacement. A cloned Wardn database
therefore cannot keep two deployments renewing as one instance: after either copy renews, the
other copy's credential is rejected. The private license service retains the customer record and
the instance name, public URL, Wardn version, activation timestamps, lease sequence, and
revocation state for every issued seat.
