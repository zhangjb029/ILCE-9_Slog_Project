"""Capture and restore the exact two source LUT properties used by A9 FL."""
from pathlib import Path
import json

from .guarded_config import LUT_IDS, require, save, save_json, sha


def load_snapshot(folder, identity):
    folder = Path(folder)
    manifest = json.loads((folder / 'snapshot.json').read_text('utf-8'))
    require(manifest.get('schema') == 'a9-fl23-lut-snapshot-v1'
            and manifest.get('identity') == identity, 'LUT snapshot identity differs')
    rows = manifest.get('tables', [])
    require([row['property_id'] for row in rows] == list(LUT_IDS),
            'LUT snapshot properties differ')
    values = {}
    for index, row in enumerate(rows):
        require(row['file'] == 'table-' + str(index) + '.bin', 'LUT snapshot path differs')
        raw = (folder / row['file']).read_bytes()
        require(len(raw) == row['bytes'] == 1280 and sha(raw) == row['sha256'],
                'LUT snapshot hash/size differs')
        values[row['property_id']] = raw
    return values


class Tables:
    def __init__(self, camera):
        self.camera = camera
        self.identity = {}

    def read(self, property_id):
        require(property_id in LUT_IDS, 'LUT property is not allowlisted')
        raw = self.camera.readBackup(property_id)
        require(isinstance(raw, bytes) and len(raw) == 1280, 'Incomplete LUT property')
        return raw

    def capture(self, folder, identity):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=False)
        self.identity = identity
        rows = []
        for index, property_id in enumerate(LUT_IDS):
            raw = self.read(property_id)
            name = 'table-' + str(index) + '.bin'
            save(folder / name, raw)
            require(self.read(property_id) == raw, 'LUT changed during capture')
            rows.append(dict(property_id=property_id, file=name,
                             bytes=len(raw), sha256=sha(raw)))
        manifest = dict(schema='a9-fl23-lut-snapshot-v1', identity=identity, tables=rows)
        save_json(folder / 'snapshot.json', manifest)
        return manifest

    def unchanged(self, values):
        require(all(self.read(property_id) == values[property_id] for property_id in LUT_IDS),
                'LUT changed during the partition operation')

    def restore(self, targets, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=False)
        self.capture(folder / 'before', self.identity)
        before = load_snapshot(folder / 'before', self.identity)
        self.camera.dev.arm_tables(targets)
        results = []
        for index, property_id in enumerate(LUT_IDS):
            require(self.read(property_id) == before[property_id], 'LUT changed before restore')
            changed = targets[property_id] != before[property_id]
            if changed:
                save_json(folder / ('write-intent-' + str(index) + '.json'),
                          dict(property_id=property_id, before_sha256=sha(before[property_id]),
                               target_sha256=sha(targets[property_id]), automatic_retry=False))
                self.camera.writeBackup(property_id, targets[property_id])
                require(self.read(property_id) == targets[property_id], 'LUT restore readback differs')
            results.append(dict(property_id=property_id, write_attempted=changed))
        self.unchanged(targets)
        changed = any(row['write_attempted'] for row in results)
        # An earlier SAVE may have lost its acknowledgement. Matching live bytes
        # alone cannot establish that the restored pair is durable.
        save_json(folder / 'save-intent.json', dict(subsystem=0, automatic_retry=False))
        self.camera.dev.arm_table_save()
        self.camera.saveBackup(0)
        self.unchanged(targets)
        save_json(folder / 'result.json', dict(verified=True, tables=results,
                                             tables_changed=changed, save_attempted=True))
        return results
