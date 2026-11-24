"""Whole-image checks after a complete read; never interrupts a transfer."""
import struct

from .guarded_config import require
from .snapshot_fs import Ext2, metadata_only_delta, runtime_metadata_regions


def compare_complete(reference, actual):
    """Permit named lifecycle metadata after receiving the complete partition."""
    changes = metadata_only_delta(reference, actual)
    return dict(verified=True, whole_partition_match=not changes,
                match_kind='EXT2_METADATA_ONLY' if changes else 'EXACT',
                ext2_changed_offsets=changes)


def verify_custom_storage(path, baseline, layout):
    """Allow the reserved object tail and known lifecycle fields only."""
    current, golden = Ext2(path), Ext2(baseline)
    require(len(current.data)==len(golden.data), 'Incomplete partition read')
    g, c = memoryview(golden.data), memoryview(current.data)
    regions = runtime_metadata_regions(golden)
    logical = 0
    object_start = layout['object_offset']
    for offset,length in golden.extents(golden.lookup('lib/a9fl.so')):
        if logical+length > object_start:
            regions.append((offset+max(0,object_start-logical),offset+length))
        logical += length
    require(logical==object_start+layout['object_blocks']*layout['object_block_length'],
            'Unexpected candidate object storage map')
    pos = 0
    for begin,end in sorted(regions)+[(len(g),len(g))]:
        require(begin>=pos and end<=len(g), 'Overlapping/out-of-range object storage map')
        require(g[pos:begin]==c[pos:begin], 'Readback differs outside known ext2 lifecycle metadata and custom LUT storage')
        pos=end
    # The contents and all saved references are checked separately by audit_state.
    return current.inode_data(current.lookup('lib/a9fl.so'))
