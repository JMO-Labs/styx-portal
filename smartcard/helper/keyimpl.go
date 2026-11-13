package helper

// CNG NCRYPT_IMPL_TYPE_PROPERTY flags.
const (
	implHardware  uint32 = 0x1 // NCRYPT_IMPL_HARDWARE_FLAG
	implRemovable uint32 = 0x8 // NCRYPT_IMPL_REMOVABLE_FLAG
)

// isSmartCardImpl reports whether a CNG key's implementation type is a
// removable hardware token (smart card), not a software or TPM key.
func isSmartCardImpl(impl uint32) bool {
	const want = implHardware | implRemovable
	return impl&want == want
}
