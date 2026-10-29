"""SHA256 with the small slice of the pycryptodomex API pmca actually uses."""
import hashlib

digest_size = 32
block_size = 64


def new(data=b''):
    return hashlib.sha256(data)


def sha256(data=b''):
    return new(data)
