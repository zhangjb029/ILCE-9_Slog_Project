"""Pinned V8 FileControl transactions with a live R15NH prerequisite audit.

The released camera payloads and installer remain byte-identical. This adapter
supplies the application's authenticated handle, checks prerequisites before
arming any write, and preserves the original installation's rollback format.
"""
import json
import posixpath
import re
import struct
import sys
import types
import uuid
from pathlib import Path

from . import file_deploy as deploy, release_assets as releases
from . import r15_files, state_fingerprints as fingerprints

ACTIONS = frozenset('v8.' + name for name in ('check', 'status', 'install', 'rollback'))
TARGETS = ('/etc/a9-autoexec-v71mt.so', '/tmp/a9-v71mt.sh', '/tmp/a9-film-boot-v71mt.tar')
PRELOAD = '/etc/ld.so.preload'
BACKUP = '/etc/a9-preload-v71mt.bak'
V71_PATHS = ('/etc/a9-autoexec-v71.so', '/tmp/a9-v71.sh', '/tmp/a9-film-boot-v71.tar')
VIEW_PATH = '/usr/lib/viewUnified2.so'
VIEW_CANONICAL_SHA = '6c1885d86feb358cf11b7f742ff2391e2dac9302ca15d1f98e91b2cff79946ba'
VIEW_EXTENT_VARIANT_SHA = '07ffd8df517022d9e661240082170ea013023fdeb76156b5510c702bc19fed9e'


def read_paths():
    """Menu reads required to classify fresh, V7.1, or V8 sources."""
    return TARGETS + (BACKUP, PRELOAD) + V71_PATHS


def load_release(manifest=None):
    raw = releases.asset('v8/deploy.py')
    module = types.ModuleType('a9_released_v8')
    module.__file__ = str(releases.ROOT / 'v8/deploy.py')
    exec(compile(raw, module.__file__, 'exec'), module.__dict__)
    canonical = releases.asset('v8/manifest.json')
    if manifest is not None and Path(manifest).read_bytes() != canonical:
        raise ValueError('V8 manifest differs from the pinned release')
    meta = json.loads(canonical)
    for row in meta['files']:
        releases.asset('v8/' + row['file'])
    payloads = module.load_package(releases.ROOT / 'v8/manifest.json')

    # Continue the factory-read initialization already performed by prerequisite
    # auditing. Switching to the mutation guard does not initialize it twice.
    original_files = module.Files
    class SharedFiles(original_files):
        def __init__(self, camera):
            if getattr(camera.dev, 'initialized', False):
                self.camera = camera
            else:
                super().__init__(camera)
    module.Files = SharedFiles
    module.save = deploy.durable
    def save_json(path, value):
        active = sys.exception()
        try:
            deploy.durable(path, (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode())
        except Exception as error:
            if active is None or Path(path).name not in ('failure.json', 'protocol.json'):
                raise
            active.add_note('Could not persist V8 ' + Path(path).name + ': ' + str(error))
    module.save_json = save_json
    return module, payloads


def _tokens(raw):
    if raw is None:
        return []
    if not isinstance(raw, bytes) or len(raw) > 16384 or b'\0' in raw:
        raise ValueError('Invalid preload data')
    text = raw.decode('ascii')
    if any(c not in '\r\n\t' and not 32 <= ord(c) < 127 for c in text):
        raise ValueError('Invalid preload control character')
    tokens = [part for line in text.splitlines()
              for part in re.split(r'[\s:]+', line.split('#', 1)[0]) if part]
    if any(not re.fullmatch(r'/[A-Za-z0-9_./+\-]+', token) for token in tokens):
        raise ValueError('Only literal absolute preload entries are supported')
    return tokens


def _canonical(token):
    token = posixpath.normpath('/' + token.lstrip('/'))
    return '/etc' + token[4:] if token.startswith('/tmp/') else token


def classify(content):
    """Classify a complete menu snapshot; this alone never grants a write."""
    observed = dict(payload_state='unknown', payloads_present=sum(content.get(p) is not None for p in TARGETS),
                    payloads_expected=len(TARGETS), preload_state='unknown')
    try:
        if any(path not in content for path in read_paths()):
            raise ValueError('V8 source reads are incomplete')
        module, payloads = load_release()
        different = any(content[path] not in (None, raw) for path, raw in zip(TARGETS, payloads.values(), strict=True))
        complete = all(content[path] == raw for path, raw in zip(TARGETS, payloads.values(), strict=True))
        observed['payload_state'] = ('different' if different else 'complete' if complete else
                                     'partial' if observed['payloads_present'] else 'absent')
        tokens = _tokens(content[PRELOAD])
        menu = [token for token in tokens if any(word in posixpath.basename(token).lower()
                                                for word in ('a9', 'a6400'))]
        observed['preload_state'] = ('v8' if menu == [TARGETS[0]] else 'v71' if menu == [V71_PATHS[0]]
                                     else 'other' if menu else 'inactive')
        if len(menu) > 1 or any(_canonical(token) not in (TARGETS[0], V71_PATHS[0]) for token in menu):
            raise ValueError('Old or unknown menu owner is active; restore its original installation first')
        if menu and menu[0] not in (TARGETS[0], V71_PATHS[0]):
            raise ValueError('Menu owner must use the exact released preload path')
        for path, raw in zip(TARGETS, payloads.values(), strict=True):
            if content[path] not in (None, raw):
                raise ValueError('Existing V8 payload differs: ' + path)
        source = 'stock'
        if menu == [V71_PATHS[0]]:
            row = next(row for row in fingerprints.index()['menus'] if row['label'] == 'V7.1')
            if any(content[path] is None or releases.sha(content[path]) != row['files'][path]
                   for path in V71_PATHS):
                raise ValueError('Active V7.1 payload set differs from the released three files')
            source = 'V7.1'
        elif menu == [TARGETS[0]]:
            source = 'V8'
        # Validate the pinned installer's preload rules as well.
        module.merge_preload(content[PRELOAD])
        complete = all(content[path] == raw for path, raw in zip(TARGETS, payloads.values(), strict=True))
        state = 'current' if source == 'V8' and complete else 'legacy' if source == 'V7.1' else 'partial' if source == 'V8' else 'stock'
        return dict(state=state, label=source, installable=True, source_label=source,
                    reason='', activation_verified=False, **observed)
    except (ValueError, UnicodeError, KeyError, StopIteration) as error:
        return dict(state='conflict', label=None, installable=False, reason=str(error),
                    activation_verified=False, **observed)


class PrerequisiteGuard:
    """One fixed read set, no mutation or terminal operation."""
    def __init__(self, transport):
        self.transport = transport
        self.initialized = False

    def sendSenserPacket(self, function, data, oData=None):
        paths = deploy.R15_PATHS + deploy.CONFIG_PATHS + read_paths()
        allowed = function == 0x10 and data == struct.pack('<HHB', 0, 0x1f, 0) and oData is None
        if function == 0x40 and len(data) >= 4:
            block, command = struct.unpack_from('<HH', data)
            body = data[4:]
            if block == 0x603:
                allowed = oData is None and command == 1 and len(body) == 4 and int.from_bytes(body, 'little') in r15_files.TABLE_IDS
            elif block == 0x1001 and command == 0x4002:
                allowed = oData is None and body == bytes(2) and not self.initialized
                if allowed:
                    self.initialized = True
            elif block == 0x1001 and command == 0x4008:
                allowed = self.initialized and body.startswith(b'\1\0\0/..') and body.endswith(b'\0') and body[6:-1].decode('ascii') in paths
        if function == 0xff01 and len(data) >= 4:
            command, size = struct.unpack_from('<HH', data)
            raw = data[4:4+size]
            name = raw.rstrip(b'\0').decode('ascii')
            allowed = (command == 2 and size > 0 and len(data) == 4+size and name in paths
                       and raw == name.encode() + bytes(4-len(name)%4))
        if not allowed:
            raise ValueError('V8 prerequisite packet outside read-only allowlist')
        return self.transport.sendSenserPacket(function, data, oData)


def r15_prerequisite(content, tables):
    """Accept one fully pinned menu variant for V8, retaining R15/CFG/LUT gates.

    Only a local comparison copy is normalized. Real camera bytes and their
    hashes remain in prerequisite evidence; no library is rewritten. This rule
    does not change the full-partition R15NH patch/source allowlist.
    """
    raw=content.get(VIEW_PATH)
    digest=releases.sha(raw) if isinstance(raw,bytes) else None
    match='canonical' if digest==VIEW_CANONICAL_SHA else 'unrecognized'
    checked=content
    if (isinstance(raw,bytes) and len(raw)==10913344 and digest==VIEW_EXTENT_VARIANT_SHA
            and struct.unpack_from('<II',raw,0x64)==(0x8c7dfc,0x8c7dfc)):
        normalized=bytearray(raw)
        struct.pack_into('<II',normalized,0x64,0x8c7e78,0x8c7e78)
        if releases.sha(normalized)==VIEW_CANONICAL_SHA:
            checked=dict(content);checked[VIEW_PATH]=bytes(normalized)
            match='known-extent-variant'
    result=fingerprints.classify_r15(checked,[content[path] for path in deploy.CONFIG_PATHS],tables)
    return dict(result,view_library_match=match,view_library_sha256=digest)


def _capture(camera):
    files = deploy.CameraFiles(camera)
    content = {path: files.read(path) for path in deploy.R15_PATHS + deploy.CONFIG_PATHS + read_paths()}
    tables = [camera.readBackup(pid) for pid in r15_files.TABLE_IDS]
    for path, raw in content.items():
        if files.read(path) != raw:
            raise ValueError('Source changed during V8 prerequisite audit: ' + path)
    if [camera.readBackup(pid) for pid in r15_files.TABLE_IDS] != tables:
        raise ValueError('Live LUT tables changed during V8 prerequisite audit')
    r15 = r15_prerequisite(content, tables)
    return content, tables, r15, classify(content)


def _path(arguments, key):
    value = arguments.get(key)
    if not isinstance(value, str) or not value or '\0' in value or not Path(value).is_absolute():
        raise ValueError(key + ' must be an absolute session path')
    return Path(value)


def execute(action, arguments, progress=None):
    if action not in ACTIONS or not isinstance(arguments, dict):
        raise ValueError('Unsupported V8 action')
    if 'recover' in arguments and type(arguments['recover']) is not bool:
        raise ValueError('recover must be an explicit boolean')
    if arguments.get('package') is not None:
        folder = _path(arguments, 'package')
        for name in ('manifest.json', 'deploy.py', 'a9-autoexec-v71mt.so',
                     'a9-v71mt.sh', 'a9-film-boot-v71mt.tar'):
            if (folder/name).read_bytes() != releases.asset('v8/'+name):
                raise ValueError('V8 package differs from the pinned release: '+name)
    module, payloads = load_release(arguments.get('manifest'))
    if action == 'v8.check':
        return dict(state='RELEASE_ASSETS_VERIFIED', payloads=len(payloads), installation_enabled=True,
                    prerequisite='R15 NAME HELP', hardware_verified=False, activation_verified=False)
    root = _path(arguments, 'session_root')
    source = _path(arguments, 'source') if action == 'v8.rollback' else None
    if source is not None:
        module.rollback_material(source)
    from . import usbdev
    say = progress or (lambda message: None)
    factory = module.FileGuard if action == 'v8.rollback' else PrerequisiteGuard
    handle = usbdev.connect(receipt=usbdev.load_current_receipt(), guard_factory=factory,
                            response_timeout=120, progress=say)
    dest = None
    try:
        identity = deploy.identity_key(handle.identity)
        if arguments.get('expected_identity') is not None and deploy.identity_key(arguments['expected_identity']) != identity:
            raise ValueError('Current camera differs from installation plan identity; no writes sent')
        if action == 'v8.rollback':
            module.rollback_material(source, identity)
            dest = root / ('v8-rollback-' + uuid.uuid4().hex)
            say('Session: ' + str(dest))
            module.rollback(handle.camera, identity, source, dest, recover=arguments.get('recover', False))
            return dict(json.loads((dest/'result.json').read_text(encoding='utf-8')),
                        session=str(dest), identity=identity, requires_cold_restart=True, activation_verified=False)
        content, tables, r15, menu = _capture(handle.camera)
        current = r15.get('label') == 'R15 NAME HELP' and r15.get('state') == 'current' and r15.get('state_validated') is True
        if action == 'v8.status':
            dest = root / ('v8-status-' + uuid.uuid4().hex)
            dest.mkdir(parents=True, exist_ok=False)
            result = dict(state='READ_ONLY_COMPLETE', session=str(dest), identity=identity,
                          r15nh_current=current, r15=r15, menu=menu, activation_verified=False)
            module.save_json(dest/'status.json', result)
            return result
        if not current:
            raise ValueError('V8 requires a live verified R15 NAME HELP installation: ' + r15.get('reason', ''))
        if not menu['installable']:
            raise ValueError(menu['reason'])
        dest = root / ('v8-install-' + uuid.uuid4().hex)
        say('Session: ' + str(dest))
        transport = handle.camera.dev.transport
        handle.camera.dev = module.FileGuard(transport)
        handle.camera.dev.initialized = True
        original_capture = module.capture
        def audited_capture(files, current_identity, folder):
            before = original_capture(files, current_identity, folder)
            if any(before[path] != content[path] for path in module.PATHS):
                raise ValueError('Menu source changed after V8 prerequisite audit')
            module.save_json(folder/'prerequisite.json', dict(identity=identity, r15=r15,
                source_menu=menu, files={path: releases.sha(raw) if raw is not None else None for path, raw in content.items()},
                table_sha256=[releases.sha(raw) for raw in tables], activation_verified=False))
            return before
        module.capture = audited_capture
        module.install(handle.camera, identity, payloads, dest)
        result = json.loads((dest/'result.json').read_text(encoding='utf-8'))
        return dict(result, session=str(dest), identity=identity, r15nh_current=True,r15=r15,
                    requires_cold_restart=True, activation_verified=False)
    except BaseException as error:
        if dest is not None:
            error.failure_session = str(dest)
            if source is not None:
                error.session = str(source)
            elif action == 'v8.install':
                try:
                    module.rollback_material(dest, deploy.identity_key(handle.identity))
                    error.session = str(dest)
                except (OSError, ValueError, KeyError):
                    error.session = None
        raise
    finally:
        handle.close()
