"""Override pyinstaller-hooks-contrib's hook for Cryptodome.

src/vendor/Cryptodome is a three-file hashlib shim, not pycryptodomex. The
contributed hook introspects the real distribution (compiled extensions,
submodules, version metadata) and raises ImportErrorWhenRunningHook when it
cannot find them — which is every clean build machine, and CI in particular.
It only builds on a machine that happens to have pycryptodomex installed, which
is exactly the kind of bug that ships.

Deliberately empty: the shim is pure Python, discovered through pathex and
pulled in by pmca's own import of Cryptodome.Hash.SHA256.
"""
