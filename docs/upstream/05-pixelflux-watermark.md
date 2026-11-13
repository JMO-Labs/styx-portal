# 05: pixelflux encoder-burned watermark

Patch: `patches/selkies/05-pixelflux-watermark.patch`. Spec and snapshot test: `agent/watermark.py`, `agent/tests/test_watermark.py`.

Burns "user + UTC time" into every frame before encode, so it appears in recordings and cannot be disabled from the browser. Text comes only from the server env (`STYX_WATERMARK_USER`).

- **Upstream project:** selkies-project/pixelflux
- **Offered:** not yet
- **Status:** local-only
- **Reason kept locally:** enterprise compliance feature (tamper-proof attribution); too product-specific to offer upstream as is.
