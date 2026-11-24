"""Pure file-level release recognition; recognition never grants a write gate.

Missing dictionary keys mean an unperformed read. Explicit None means verified
absence. Mutable object tails are excluded only by a pinned source layout.
"""
import hashlib
import posixpath
import re
from functools import lru_cache
from . import data


@lru_cache(maxsize=1)
def index():
    return data.resource_json('state_fingerprints.json')


R15_PATHS = tuple(index()['r15'][0]['files'])
MENU_PATHS = tuple(sorted({p for row in index()['menus'] for p in row['files']} |
                         {'/etc/ld.so.preload', '/etc/A9BOOT/A9BOOT.SO'}))


def _digest(raw):
    return None if raw is None else hashlib.sha256(raw).hexdigest()


def _result(state, label=None, reason='', **extra):
    return dict(state=state, label=label, supported=state in ('stock','legacy','current'),
                upgrade_enabled=False, reason=reason, **extra)


def classify_r15(files, configs=None, tables=None, *, partition_upgrade=False):
    if any(p not in files for p in R15_PATHS):
        return _result('unknown', reason='Required file reads are missing')
    if any(v is not None and not isinstance(v, bytes) for p,v in files.items() if p in R15_PATHS):
        return _result('unknown', reason='File values must be complete bytes or verified absence')
    actual = {p:_digest(files[p]) for p in R15_PATHS}
    for row in index()['r15']:
        matched = True
        for path, expected in row['files'].items():
            if path == '/usr/lib/a9fl.so' and row.get('object_layout'):
                layout = row['object_layout']; raw = files[path]; offset = layout['object_offset']
                ok = (raw is not None and len(raw) == offset+layout['object_blocks']*layout['object_block_length']
                      and _digest(raw[:offset]) == layout['immutable_prefix_sha256'])
            else:
                ok = actual.get(path) == expected
            if not ok:
                matched = False; break
        if not matched:
            continue
        state = 'stock' if row['label']=='stock' else 'current' if row['label']=='R15 NAME HELP' else 'legacy'
        result = _result(state, row['label'], 'File identity recognized; owner/snapshot replacement gate remains closed',
                         config_schema=row.get('config_schema'), object_layout=row.get('object_layout'),
                         state_validated=False, source=row['source'],
                         preparation_supported=row['label'] in ('R14 FIX1','R15','R15 NAME HELP'))
        if configs is not None:
            from . import r15_files
            try:
                if len(configs) != 4:
                    raise ValueError('Four configuration records required')
                records = [r15_files.decode_record(name,raw) if raw is not None else None
                           for name,raw in zip(r15_files.CONFIG_NAMES,configs)]
                # R9 itself misreads valid older A9 records. The R15NH target
                # accepts their published schema and migrates them on load.
                if row['label']=='R9' and not partition_upgrade and any(r and configs[i][:2]==b'A9' for i,r in enumerate(records)):
                    raise ValueError('R9 has a known A7/A9 configuration identity incompatibility')
                if row['label']=='stock' and any(records):
                    raise ValueError('Stock files coexist with custom FL configuration')
                if any(r and r['schema'] > row['config_schema'] for r in records):
                    raise ValueError('Configuration schema newer than recognized module')
                allowed = {1, *range(4, (row.get('config_schema') or 0)+1)}
                if any(r and r['schema'] not in allowed for r in records):
                    raise ValueError('Configuration schema is not an accepted published source format')
                result['config_records_validated'] = True
                # Full object-reference/table validation is implemented for the
                # three supported preparation profiles, separately from identity.
                profiles = {'R14':'R14-SD','R14 FIX1':'R14-SD','R15':'R15-ORIGINAL','R15 NAME HELP':'R15-SD'}
                if tables is not None and row['label'] in profiles:
                    audit = r15_files.audit_state(files['/usr/lib/a9fl.so'], configs, tables,
                                                 profiles[row['label']], row['object_layout'])
                    if audit['live_pair']['status']=='no-record-pair-match':
                        raise ValueError('Live table pair does not match records or factory')
                    result['state_validated'] = True
            except (ValueError, TypeError, IndexError) as error:
                return _result('conflict', row['label'], str(error))
        return result
    # A mixture of individually known files is not an exact release.
    known = {p:{r['files'][p] for r in index()['r15']} for p in R15_PATHS}
    recognized = sum(actual[p] in known[p] for p in R15_PATHS)
    return _result('partial' if recognized else 'unknown', reason='No complete recognized five-file release')


def classify_v7(files):
    if any(p not in files for p in MENU_PATHS):
        return _result('unknown', reason='Legacy and current menu file reads are incomplete')
    preload = files['/etc/ld.so.preload']
    if preload is not None and not isinstance(preload, bytes):
        return _result('unknown', reason='Invalid preload data')
    try:
        text = '' if preload is None else preload.decode('ascii')
        if len(text)>16384 or any(ord(c)<32 and c not in '\r\n\t' for c in text):
            raise UnicodeDecodeError('ascii', b'', 0, 1, 'Invalid preload controls/length')
        tokens = [word for line in text.splitlines() for word in re.split(r'[\s:]+',line.split('#',1)[0]) if word]
        if any(not re.fullmatch(r'/[A-Za-z0-9_./+\-]+',token) for token in tokens):
            return _result('conflict', reason='Nonliteral or relative preload path')
    except UnicodeDecodeError:
        return _result('conflict', reason='Unrecognized preload encoding')
    def canonical(token):
        value=posixpath.normpath('/'+token.lstrip('/'))
        return '/etc'+value[4:] if value.startswith('/tmp/') else value
    tokens=[canonical(token) for token in tokens]
    hooks={canonical(r['hook']) for r in index()['menus']}
    menu_tokens=[t for t in tokens if t in hooks or 'a9' in posixpath.basename(t).lower() or 'a6400' in posixpath.basename(t).lower()]
    if len(menu_tokens) != len(set(menu_tokens)):
        return _result('conflict', reason='Duplicate preload entries')
    if len(menu_tokens)>1 or any(t not in hooks for t in menu_tokens):
        return _result('conflict', reason='Unknown or multiple menu preload owners')
    present = {p for p in MENU_PATHS if p != '/etc/ld.so.preload' and files[p] is not None}
    if not present:
        return _result('partial' if menu_tokens else 'stock', reason='Menu files absent; unrelated preload retained')
    matches = []
    for row in index()['menus']:
        expected = dict(row['files'])
        if row['label'] in ('V3','V3.1'):
            expected['/etc/A9BOOT/A9BOOT.SO'] = expected['/tmp/A9BOOT/A9BOOT.SO']
        if all(p in files and _digest(files[p]) == digest for p,digest in expected.items()):
            matches.append((row,expected))
    active = [(r,expected) for r,expected in matches if menu_tokens == [canonical(r['hook'])]]
    if len(active) == 1:
        row,expected = active[0]
        known={p:set() for p in MENU_PATHS}
        for release in index()['menus']:
            for path,digest in release['files'].items():
                known.setdefault(path,set()).add(digest)
            if release['label'] in ('V3','V3.1'):
                known['/etc/A9BOOT/A9BOOT.SO'].add(release['files']['/tmp/A9BOOT/A9BOOT.SO'])
        if any(_digest(files[p]) not in known[p] for p in present-expected.keys()):
            return _result('conflict', row['label'], 'Unknown inactive menu file bytes; explicit review required')
        return _result('current' if row['label']=='V7' else 'legacy', row['label'],
                       'Complete payload and preload identity recognized; migration needs original backups',
                       source=row['source'],source_label=row['label'],hook=row['hook'],
                       aliases=row.get('aliases',[]),
                       migration_supported=row['label'] not in ('V7','V7.1'),
                       inactive_files_preserved=sorted(present-expected.keys()))
    return _result('partial', reason='Menu payload set/preload does not form an active complete release')
