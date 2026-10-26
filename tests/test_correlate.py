"""Protein-correlation matrix: replicate gels of one protein must average into
one row, not appear as separate rows (regression for the dugiel->dubiel
public-release pass, where combined_corr_proteins.png showed each replicate as
its own "protein")."""
import numpy as np

from dubiel.gelanalyzer.correlate import _protein_lane_pct


def _entry(protein, pct_by_lane):
    import pandas as pd
    rows = [{"lane_label": lane, "is_ladder": False, "adjusted_volume": pct,
             "raw_intensity": pct} for lane, pct in pct_by_lane.items()]
    import types
    return types.SimpleNamespace(protein_label=protein,
                                 result_df=pd.DataFrame(rows))


def test_replicate_entries_average_into_one_protein_row():
    # Two replicate gels of "target", one gel of "loading" -- same lane names.
    entries = [
        _entry("target", {"control": 100.0, "treated": 40.0}),
        _entry("target", {"control": 100.0, "treated": 60.0}),
        _entry("loading", {"control": 100.0, "treated": 95.0}),
    ]
    proteins, lanes, mat = _protein_lane_pct(entries)

    assert proteins == ["target", "loading"], proteins
    assert len(proteins) == 2  # not 3 -- replicates must not double-count
    i_target, i_loading = proteins.index("target"), proteins.index("loading")
    i_control, i_treated = lanes.index("control"), lanes.index("treated")
    # treated% is averaged across the two "target" replicates: (40+60)/2 = 50
    assert abs(mat[i_target, i_treated] - 50.0) < 1e-9
    assert abs(mat[i_loading, i_treated] - 95.0) < 1e-9
    assert mat[i_target, i_control] == 100.0


if __name__ == "__main__":
    test_replicate_entries_average_into_one_protein_row()
    print("test_correlate.py self-check OK")
