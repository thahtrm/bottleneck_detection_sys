"""Kiểm thử tự động cho quy trình ETL MongoDB -> DuckDB và driver build_duckdb."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb
import numpy as np

from jira_adapter.build_duckdb import build_instance_duckdb, fetch_instance_from_duckdb
from jira_adapter.etl.loader import DuckDBLoader
from jira_adapter.etl.transformer import JiraTransformer


class TestETL(unittest.TestCase):
    def setUp(self) -> None:
        self.transformer = JiraTransformer(preview_len=50)

        # Document mẫu chứa đầy đủ các ca dị dạng thực tế của The Public Jira Dataset
        self.sample_doc = {
            "key": "TEST-101",
            "fields": {
                "summary": "Fix critical database deadlock",
                "issuetype": {"name": "Bug"},
                "priority": {"name": "1 - Blocker"},
                "status": {"name": "Resolved"},
                "resolution": {"name": "Fixed"},
                "created": "2021-05-01T10:00:00.000+0000",
                "updated": "2021-05-02T12:00:00.000+0000",
                "resolutiondate": "2021-05-02T12:00:00.000+0000",
                "assignee": {"name": "<<|author_name|uuid-123|>>"},
                "reporter": {"name": "<<|author_name|uuid-456|>>"},
                "issuelinks": [
                    {
                        "type": {"name": "Blocks"},
                        "outwardIssue": {"key": "TEST-101"},
                        "inwardIssue": {"key": "TEST-102"},
                    },
                    {
                        "type": {"name": "Relates"},
                        "outwardIssue": {"key": "TEST-103"},
                        "inwardIssue": {"key": "TEST-101"},
                    },
                ],
                "comments": [
                    {
                        "id": "c1",
                        "author": {"name": "reviewer"},
                        "created": "2021-05-01T11:00:00.000+0000",
                        "body": "Investigating the deadlock trace.",
                    }
                ],
            },
            "changelog": {
                "startAt": 0,
                "maxResults": 2,
                "total": 2,
                "histories": [
                    {
                        "id": "h1",
                        "author": {"name": "alice"},
                        "created": "2021-05-01T10:30:00.000+0000",
                        "items": [
                            {"field": "status", "from": "Open", "set": "In Progress"}
                        ],
                    },
                    {
                        "id": "h2",
                        "author": {"name": "bob"},
                        "created": "2021-05-02T12:00:00.000+0000",
                        "items": [
                            {"field": "status", "from": "In Progress", "set": "Resolved"},
                            {"field": "priority", "from": "High", "to": "Blocker"},
                        ],
                    },
                ],
            },
        }

    def test_transformer(self) -> None:
        out = self.transformer.transform_doc(self.sample_doc, instance="TestInst")

        # 1. Bảng issues
        self.assertEqual(len(out["issues"]), 1)
        issue = out["issues"][0]
        self.assertEqual(issue[0], "TestInst")
        self.assertEqual(issue[1], "TEST-101")
        self.assertEqual(issue[2], "TEST")
        self.assertEqual(issue[4], "Bug")
        self.assertEqual(issue[5], "Maintenance")  # Bug -> Maintenance theme
        self.assertEqual(issue[7], 1.0)  # 1 - Blocker -> 1.0
        self.assertEqual(issue[8], "Resolved")
        self.assertTrue(issue[18])  # has_block_or_depend == True

        # 2. Bảng changelogs
        self.assertEqual(len(out["changelogs"]), 3)
        fields = [ch[5] for ch in out["changelogs"]]
        self.assertEqual(fields, ["status", "status", "priority"])

        # 3. Bảng links
        self.assertEqual(len(out["links"]), 2)
        link_types = [lk[4] for lk in out["links"]]
        self.assertIn("Block", link_types)
        self.assertIn("Relate", link_types)

        # 4. Bảng comments
        self.assertEqual(len(out["comments"]), 1)
        self.assertEqual(out["comments"][0][3], "reviewer")
        self.assertEqual(out["comments"][0][5], len("Investigating the deadlock trace."))

    def test_loader_and_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = str(Path(tmpdir) / "test_loader.duckdb")
            loader = DuckDBLoader(duckdb_path=tmp_path)
            loader.init_schema()

            # Nạp dữ liệu
            batch_data = self.transformer.transform_batch([self.sample_doc], instance="TestInst")
            loader.load_batch(batch_data)

            stats = loader.get_instance_stats("TestInst")
            self.assertEqual(stats["n_issues"], 1)
            self.assertEqual(stats["n_changelogs"], 3)
            self.assertEqual(stats["n_links"], 2)
            self.assertEqual(stats["n_comments"], 1)
            # v_tgn_events = 3 changelogs + 2 links + 1 comment = 6
            self.assertEqual(stats["n_tgn_events"], 6)

            # Kiểm tra truy vấn trực tiếp view
            con = duckdb.connect(tmp_path)
            events = con.execute(
                "SELECT kind, COUNT(*) FROM v_tgn_events WHERE instance = 'TestInst' GROUP BY kind"
            ).fetchall()
            event_counts = dict(events)
            self.assertEqual(event_counts["status"], 2)
            self.assertEqual(event_counts["priority"], 1)
            self.assertEqual(event_counts["link"], 2)
            self.assertEqual(event_counts["comment"], 1)

            # Kiểm tra xóa idempotency
            loader.clear_instance("TestInst")
            stats_cleared = loader.get_instance_stats("TestInst")
            self.assertEqual(stats_cleared["n_issues"], 0)
            self.assertEqual(stats_cleared["n_tgn_events"], 0)

            con.close()
            loader.close()

    def test_build_duckdb_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            duck_path = str(Path(tmpdir) / "test.duckdb")
            loader = DuckDBLoader(duckdb_path=duck_path)
            loader.init_schema()

            # Tạo 2 issue liên kết nhau
            doc1 = dict(self.sample_doc)
            doc2 = {
                "key": "TEST-102",
                "fields": {
                    "summary": "Target issue",
                    "issuetype": {"name": "Task"},
                    "priority": {"name": "Major"},
                    "status": {"name": "Open"},
                    "created": "2021-05-01T10:05:00.000+0000",
                    "updated": "2021-05-01T10:05:00.000+0000",
                },
                "changelog": [],
                "issueLinks": [],
                "comments": [],
            }

            batch_data = self.transformer.transform_batch([doc1, doc2], instance="TestInst")
            loader.load_batch(batch_data)
            loader.close()

            # Chạy build_instance_duckdb
            res = build_instance_duckdb(
                name="TestInst",
                duckdb_path=duck_path,
                out_dir=tmpdir,
                mode="dependency",
                leak_safe=True,
            )

            self.assertEqual(res["n_docs"], 2)
            self.assertTrue(Path(tmpdir, "ml_TestInst.csv").exists())
            self.assertTrue(Path(tmpdir, "ml_TestInst.npy").exists())
            self.assertTrue(Path(tmpdir, "ml_TestInst_node.npy").exists())

            # Kiểm tra shape của numpy features
            edge_feats = np.load(Path(tmpdir, "ml_TestInst.npy"))
            node_feats = np.load(Path(tmpdir, "ml_TestInst_node.npy"))

            self.assertEqual(edge_feats.shape[1], 24)
            self.assertEqual(node_feats.shape[1], 64)  # default padded node_out_dim


if __name__ == "__main__":
    unittest.main()
