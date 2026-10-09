"""The add-on bundles its own copy of the integration (the add-on build context cannot
reach the repository root), and HACS installs from custom_components/ at the root.
Both copies must stay identical."""
import filecmp
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HACS = ROOT / "custom_components/meteo_ua"
ADDON = ROOT / "meteo-ua-weather/rootfs/app/bundle/custom_components/meteo_ua"


def _diff(cmp: filecmp.dircmp, prefix: str = "") -> list[str]:
    out = [prefix + n for n in cmp.left_only + cmp.right_only + cmp.diff_files + cmp.funny_files
           if n != "__pycache__"]
    for name, sub in cmp.subdirs.items():
        if name != "__pycache__":
            out += _diff(sub, f"{prefix}{name}/")
    return out


class BundleSyncTest(unittest.TestCase):
    def test_hacs_and_addon_copies_match(self):
        filecmp.clear_cache()
        self.assertEqual(_diff(filecmp.dircmp(HACS, ADDON)), [])


if __name__ == "__main__":
    unittest.main()
