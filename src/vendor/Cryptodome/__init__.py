"""Minimal stand-in for pycryptodomex.

pmca imports ``Cryptodome.Hash.SHA256`` at module load and calls exactly one
method on it. Shipping the real distribution would put an 8 MB compiled
extension into the release and tie the build to one CPython ABI; hashlib gives
the same digest from the standard library.
"""
