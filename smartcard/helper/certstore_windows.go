//go:build windows

package helper

import (
	"crypto"
	"encoding/asn1"
	"crypto/ecdsa"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"io"
	"math/big"
	"syscall"
	"time"
	"unsafe"
)

var (
	crypt32         = syscall.NewLazyDLL("crypt32.dll")
	ncrypt          = syscall.NewLazyDLL("ncrypt.dll")
	pOpenStore      = crypt32.NewProc("CertOpenSystemStoreW")
	pEnumCerts      = crypt32.NewProc("CertEnumCertificatesInStore")
	pAcquireKey     = crypt32.NewProc("CryptAcquireCertificatePrivateKey")
	pNCryptSignHash = ncrypt.NewProc("NCryptSignHash")
	acquireOnlyNCNG = uintptr(0x00040000)
	bcryptPadPKCS1  = uintptr(0x2)
	bcryptPadPSS    = uintptr(0x8)
)

type certContext struct {
	EncodingType uint32
	Encoded      *byte
	Length       uint32
	Info         uintptr
	Store        uintptr
}

type winCertStore struct{}

// ClientCert picks the first valid client-auth cert in the user's MY store
// whose private key is reachable through CNG (smart-card minidriver).
func (winCertStore) ClientCert() (tls.Certificate, error) {
	name, _ := syscall.UTF16PtrFromString("MY")
	store, _, _ := pOpenStore.Call(0, uintptr(unsafe.Pointer(name)))
	if store == 0 {
		return tls.Certificate{}, errors.New("cannot open certificate store")
	}
	var prev uintptr
	for {
		ctx, _, _ := pEnumCerts.Call(store, prev)
		if ctx == 0 {
			return tls.Certificate{}, errors.New("no usable smart-card certificate found")
		}
		prev = ctx
		cc := (*certContext)(unsafe.Pointer(ctx))
		der := append([]byte(nil), unsafe.Slice(cc.Encoded, cc.Length)...)
		crt, err := x509.ParseCertificate(der)
		if err != nil || !clientAuthOK(crt) {
			continue
		}
		var key uintptr
		var spec uint32
		var free int32
		r, _, _ := pAcquireKey.Call(ctx, acquireOnlyNCNG, 0,
			uintptr(unsafe.Pointer(&key)), uintptr(unsafe.Pointer(&spec)), uintptr(unsafe.Pointer(&free)))
		if r == 0 {
			continue
		}
		return tls.Certificate{Certificate: [][]byte{der}, PrivateKey: &ncryptSigner{key: key, pub: crt.PublicKey}, Leaf: crt}, nil
	}
}

func clientAuthOK(c *x509.Certificate) bool {
	now := time.Now()
	if now.Before(c.NotBefore) || now.After(c.NotAfter) {
		return false
	}
	for _, u := range c.ExtKeyUsage {
		if u == x509.ExtKeyUsageClientAuth || u == x509.ExtKeyUsageAny {
			return true
		}
	}
	return false
}

type ncryptSigner struct {
	key uintptr
	pub crypto.PublicKey
}

func (s *ncryptSigner) Public() crypto.PublicKey { return s.pub }

var hashNames = map[crypto.Hash]string{
	crypto.SHA1: "SHA1", crypto.SHA256: "SHA256", crypto.SHA384: "SHA384", crypto.SHA512: "SHA512",
}

type pkcs1Info struct{ Alg *uint16 }
type pssInfo struct {
	Alg  *uint16
	Salt uint32
}

// Sign signs a digest with the card key via NCryptSignHash (may prompt for PIN).
func (s *ncryptSigner) Sign(_ io.Reader, digest []byte, opts crypto.SignerOpts) ([]byte, error) {
	var padInfo unsafe.Pointer
	var flags uintptr
	if _, isRSA := s.pub.(*rsa.PublicKey); isRSA {
		alg, ok := hashNames[opts.HashFunc()]
		if !ok {
			return nil, errors.New("unsupported hash")
		}
		algp, _ := syscall.UTF16PtrFromString(alg)
		if pss, ok := opts.(*rsa.PSSOptions); ok {
			salt := pss.SaltLength
			if salt == rsa.PSSSaltLengthEqualsHash || salt == rsa.PSSSaltLengthAuto {
				salt = opts.HashFunc().Size()
			}
			pi := pssInfo{Alg: algp, Salt: uint32(salt)}
			padInfo, flags = unsafe.Pointer(&pi), bcryptPadPSS
		} else {
			pi := pkcs1Info{Alg: algp}
			padInfo, flags = unsafe.Pointer(&pi), bcryptPadPKCS1
		}
	}
	var n uint32
	call := func(out *byte, size uint32) uintptr {
		r, _, _ := pNCryptSignHash.Call(s.key, uintptr(padInfo), uintptr(unsafe.Pointer(&digest[0])), uintptr(len(digest)),
			uintptr(unsafe.Pointer(out)), uintptr(size), uintptr(unsafe.Pointer(&n)), flags)
		return r
	}
	if r := call(nil, 0); r != 0 {
		return nil, scardErr("NCryptSignHash(size)", r)
	}
	sig := make([]byte, n)
	if r := call(&sig[0], n); r != 0 {
		return nil, scardErr("NCryptSignHash", r)
	}
	sig = sig[:n]
	if _, isEC := s.pub.(*ecdsa.PublicKey); isEC {
		h := len(sig) / 2
		return asn1.Marshal(struct{ R, S *big.Int }{new(big.Int).SetBytes(sig[:h]), new(big.Int).SetBytes(sig[h:])})
	}
	return sig, nil
}
