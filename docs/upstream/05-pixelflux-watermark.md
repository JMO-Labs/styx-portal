# 05: pixelflux encoder-burned watermark

Patch: `patches/selkies/05-pixelflux-watermark.patch`. Spec and snapshot test: `agent/watermark.py`, `agent/tests/test_watermark.py`.

Burns "user + UTC time" into every frame before encode, so it appears in recordings and cannot be disabled from the browser. Text comes only from the server env (`STYX_WATERMARK_USER`).

- **Upstream project:** selkies-project/pixelflux
- **Offered:** not yet
- **Status:** local-only
- **Reason kept locally:** enterprise compliance feature (tamper-proof attribution); too product-specific to offer upstream as is.

Scope: the patch stamps the CPU capture path (BGRA buffers, stride aware) ahead of every encoder fed from it. The zero-copy GPU dmabuf path has no CPU pixels and is not stamped; force the CPU path where attribution is required. The Rust tests pin the same values as the Python spec (`SPEC_FNV`, `SPEC_PIXELS`); `agent/tests/test_watermark.py` also parses the patch to check the env var is the only input and there are no mutators.
